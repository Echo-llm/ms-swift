import os
from functools import partial
from typing import Any, Dict, List, Union

from datasets import Dataset as HfDataset
from transformers import IntervalStrategy

from swift.plugin import extra_callbacks, get_loss_func, optimizers_map
from swift.trainers import TrainerFactory
from swift.utils import (append_to_jsonl, check_json_format, compute_acc_metrics, compute_nlg_metrics, get_dist_setting,
                         get_logger, get_model_parameter_info, is_ddp_plus_mp, is_dist, is_master, plot_images,
                         preprocess_logits_for_acc, seed_everything, show_layers, stat_array, use_torchacc)
from ..argument import TrainArguments
from ..base import SwiftPipeline
from ..dataset import ConstantLengthDataset, EncodePreprocessor, GetLengthPreprocessor, LazyLLMDataset, load_dataset
from ..infer import RequestConfig, prepare_generation_config
from ..model import ModelInfo, ModelMeta, get_model_arch, get_model_tokenizer
from ..template import Template, get_template
from ..tuner import prepare_tuner
from ..utils import deep_getattr, dynamic_gradient_checkpointing

logger = get_logger()


class SwiftSft(SwiftPipeline):
    args_class = TrainArguments
    args: args_class

    def __init__(self, args: Union[List[str], TrainArguments, None] = None) -> None:
        super().__init__(args)
        self.train_msg = {}
        self._prepare_model_tokenizer()
        self._prepare_template()
        self._prepare_callbacks()
        self.model = prepare_tuner(self.model, args)
        logger.info(self.model)
        model_parameter_info = get_model_parameter_info(self.model)
        self.train_msg['model_parameter_info'] = model_parameter_info
        logger.info(f'model_parameter_info: {model_parameter_info}')

        self._prepare_train()

    def _prepare_train(self):
        self.template.set_mode('train')

    def _prepare_gradient_checkpointing(self):
        args = self.args
        dynamic_gradient_checkpointing(self.model)

        if args.gradient_checkpointing:
            self.model.config.use_cache = False  # fix transformers==4.36
            logger.info('Setting model.config.use_cache: False')
            self.model.enable_input_require_grads()
        model_meta = self.model.model_meta
        model_arch = get_model_arch(model_meta.model_arch)
        if model_meta.is_multimodal and model_arch:
            for vision_tower_name in model_arch.vision_tower:
                vision_tower = deep_getattr(self.model, vision_tower_name)
                if args.vit_gradient_checkpointing:
                    if hasattr(vision_tower, 'enable_input_require_grads'):
                        try:
                            vision_tower.enable_input_require_grads()
                        except NotImplementedError:
                            pass
                else:
                    self.model.gradient_checkpointing_disable()

    def _prepare_generation_config(self):
        args = self.args
        self.model.generation_config = prepare_generation_config(self.model.generation_config,
                                                                 args.get_request_config(False))
        logger.info(f'model.generation_config: {self.model.generation_config}')

    def _get_model_tokenizer(self, model, model_type, model_revision):
        args = self.args
        return get_model_tokenizer(
            model,
            args.torch_dtype,
            args.device_map,
            model_type=model_type,
            revision=model_revision,
            quantization_config=args.quantization_config,
            attn_impl=args.attn_impl,
            rope_scaling=args.rope_scaling,
            use_unsloth=args.tuner_backend == 'unsloth')

    def _prepare_model_tokenizer(self):
        args = self.args
        self.model, self.tokenizer = self._get_model_tokenizer(args.model, args.model_type, args.model_revision)

        if hasattr(self.model, 'hf_device_map'):
            logger.info(f'model.hf_device_map: {self.model.hf_device_map}')

        logger.info(f'model_config: {self.model.config}')

        self._prepare_generation_config()
        self._prepare_gradient_checkpointing()

    def _prepare_template(self, **template_kwargs) -> None:
        args = self.args
        template = get_template(
            args.template,
            self.tokenizer,
            args.system,
            args.max_length,
            truncation_strategy=args.truncation_strategy,
            max_pixels=args.max_pixels,
            loss_scale=args.loss_scale,
            tools_prompt=args.tools_prompt,
            sequence_parallel_size=args.sequence_parallel_size,
            **template_kwargs)
        logger.info(f'default_system: {template.default_system}')
        self.template = template

    def _get_dataset(self):
        args = self.args
        dataset_kwargs = {
            'seed': args.data_seed,
            'num_proc': args.dataset_num_proc,
            'load_from_cache_file': args.load_from_cache_file,
            'download_mode': args.download_mode,
            'model_name': args.model_name,
            'model_author': args.model_author,
            'streaming': args.streaming,
            'streaming_val_size': args.streaming_val_size,
            'streaming_buffer_size': args.streaming_buffer_size,
            'strict': args.strict
        }

        if len(args.val_dataset) > 0:
            # Loading val dataset
            _, val_dataset = load_dataset(args.val_dataset, 1.0, **dataset_kwargs)
            args.split_dataset_ratio = 0
        train_dataset, val_dataset = load_dataset(args.dataset, args.split_dataset_ratio, **dataset_kwargs)
        logger.info(f'train_dataset: {train_dataset}')
        logger.info(f'val_dataset: {val_dataset}')

        return train_dataset, val_dataset

    def _get_compute_loss(self):
        args = self.args
        loss_type = args.loss_type
        if loss_type is None and args.loss_scale != 'default':
            loss_type = 'loss-scale'
        return get_loss_func(loss_type)

    def _get_data_collator(self):
        args = self.args
        template = self.template
        padding_to = args.max_length if args.train_type == 'longlora' else None
        is_multimodal = self.model.model_meta.is_multimodal
        if is_multimodal:
            data_collator = template.pre_data_collator
            self._register_post_encode_hook()
        else:
            data_collator = template.data_collator
        return partial(data_collator, padding_to=padding_to, model=self.model)

    def _register_post_encode_hook(self):
        template.register_post_encode_hook([self.model])

    def run(self):
        args = self.args

        train_dataset, val_dataset = self._get_dataset()
        train_dataset, val_dataset = self._encode_dataset(train_dataset, val_dataset)

        data_collator = self._get_data_collator()

        optimizers = self._get_optimizers(train_dataset)

        trainer_cls = TrainerFactory.get_trainer_cls(args)
        trainer = trainer_cls(
            model=self.model,
            args=self.args.training_args,
            data_collator=data_collator,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            callbacks=self.callbacks,
            optimizers=optimizers,
            tokenizer=self.tokenizer,
            **self._get_trainer_kwargs(),
        )
        return self.train(trainer)

    def _get_trainer_kwargs(self):
        args = self.args
        if args.predict_with_generate:
            compute_metrics = partial(compute_nlg_metrics, tokenizer=tokenizer)
            preprocess_logits_for_metrics = None
        else:
            compute_metrics = partial(
                compute_acc_metrics,
                acc_strategy=args.acc_strategy,
                is_encoder_decoder=self.model.config.is_encoder_decoder)
            compute_metrics = compute_metrics
            preprocess_logits_for_metrics = preprocess_logits_for_acc

        return {
            'compute_metrics': compute_metrics,
            'preprocess_logits_for_metrics': preprocess_logits_for_metrics,
            'compute_loss_func': self._get_compute_loss()
        }

    def _save_trainer_state(self, trainer):
        training_args = trainer.args
        state = trainer.state

        logger.info(f'last_model_checkpoint: {state.last_model_checkpoint}')
        logger.info(f'best_model_checkpoint: {state.best_model_checkpoint}')

        # Visualization
        if is_master() and not use_torchacc():
            if 'tensorboard' in training_args.report_to:
                images_dir = os.path.join(training_args.output_dir, 'images')
                logger.info(f'images_dir: {images_dir}')
                plot_images(images_dir, training_args.logging_dir, ['train/loss'], 0.9)
            if training_args.push_to_hub:
                trainer.push_to_hub()

        self.train_msg.update({
            'last_model_checkpoint': state.last_model_checkpoint,
            'best_model_checkpoint': state.best_model_checkpoint,
            'best_metric': state.best_metric,
            'global_step': state.global_step,
            'log_history': state.log_history,
            'memory': trainer.max_memory,
        })
        if is_master():
            jsonl_path = os.path.join(training_args.output_dir, 'logging.jsonl')
            append_to_jsonl(jsonl_path, self.train_msg)
        return self.train_msg

    def train(self, trainer):
        logging_path = os.path.join(trainer.args.output_dir, 'logging.jsonl')
        logger.info(f'The logging file will be saved in: {logging_path}')
        trainer.model_accepts_loss_kwargs = True  # fix transformers>=4.46.2
        trainer.train(trainer.args.resume_from_checkpoint)

        return self._save_trainer_state(trainer)

    def _get_optimizers(self, train_dataset):
        args = self.args
        optimizer_callback = optimizers_map['default']
        if args.lorap_lr_ratio:
            optimizer_callback = optimizers_map['lorap']
        if args.use_galore:
            if args.galore_target_modules is None:
                args.galore_target_modules = find_all_linears(model, 0, args.model_type, args.quant_method)
            if args.galore_with_embedding:
                args.galore_target_modules += find_embedding(model)
            optimizer_callback = optimizers_map['galore']

        return optimizer_callback(self.model, train_dataset, args)

    def _prepare_callbacks(self):
        args = self.args
        callbacks = []
        if args.lisa_activated_layers > 0:
            assert args.train_type == 'full', 'LISA only supports full parameter training.'
            lisa_callback = DynamicLayerActivationCallback(
                n_layers=args.lisa_activated_layers,  # Number of layers to activate
                step_interval=args.lisa_step_interval,  # Step interval to update active layers
                model=model)
            lisa_callback.switch_active_layers()  # Make trainable parameters printing a correct value
            callbacks.append(lisa_callback)

        if args.is_adapter and args.tuner_backend == 'swift':
            callbacks.append(TrainerAdapterCallback(args))
        callbacks += extra_callbacks
        self.callbacks = callbacks

    def _stat_dataset(self, dataset: HfDataset):
        args = self.args
        dataset = GetLengthPreprocessor()(
            dataset, num_proc=args.dataset_num_proc, load_from_cache_file=args.load_from_cache_file)
        _, stat_str = stat_array(dataset['length'])
        logger.info(f'Dataset Token Length: {stat_str}')
        return stat_str

    def _encode_dataset(self, train_dataset, val_dataset):
        template = self.template
        args = self.args

        if args.lazy_tokenize:
            train_dataset = LazyLLMDataset(
                train_dataset, template.encode, strict=args.strict, random_state=args.data_seed)
            if val_dataset is not None:
                val_dataset = LazyLLMDataset(
                    val_dataset, template.encode, strict=args.strict, random_state=args.data_seed)
        elif args.packing:
            train_dataset = ConstantLengthDataset.get_packed_dataset(
                template, train_dataset, args.max_length, lazy_tokenize=args.lazy_tokenize)
            if val_dataset is not None:
                val_dataset = ConstantLengthDataset.get_packed_dataset(
                    template, val_dataset, args.max_length, lazy_tokenize=args.lazy_tokenize)
        else:
            train_dataset = EncodePreprocessor(template)(
                train_dataset, num_proc=args.dataset_num_proc, load_from_cache_file=args.load_from_cache_file)
            if val_dataset is not None:
                val_dataset = EncodePreprocessor(template)(
                    val_dataset, num_proc=args.dataset_num_proc, load_from_cache_file=args.load_from_cache_file)

        inputs = train_dataset[0] if isinstance(train_dataset, HfDataset) else next(iter(train_dataset))
        template.print_inputs(inputs)
        if isinstance(train_dataset, HfDataset):
            self.train_msg['train_dataset'] = self._stat_dataset(train_dataset)
            if val_dataset is not None:
                self.train_msg['val_dataset'] = self._stat_dataset(val_dataset)

        return train_dataset, val_dataset


def sft_main(args: Union[List[str], TrainArguments, None] = None):
    return SwiftSft(args).main()
