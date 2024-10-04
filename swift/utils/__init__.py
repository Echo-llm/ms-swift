# Copyright (c) Alibaba, Inc. and its affiliates.

from .env import use_hf_hub
from .import_utils import (is_liger_available, is_lmdeploy_available, is_megatron_available, is_unsloth_available,
                           is_vllm_available, is_xtuner_available)
from .io_utils import append_to_jsonl, read_from_jsonl, write_to_jsonl
from .logger import get_logger
from .metric import compute_acc_metrics, compute_nlg_metrics, preprocess_logits_for_metrics
from .np_utils import get_seed, stat_array, transform_jsonl_to_df
from .run_utils import get_main
from .tb_utils import TB_COLOR, TB_COLOR_SMOOTH, plot_images, read_tensorboard_file, tensorboard_smoothing
from .torch_utils import (activate_model_parameters, broadcast_string, freeze_model_parameters, get_dist_setting,
                          get_model_info, is_ddp_plus_mp, is_dist, is_dist_ta, is_local_master, is_master, is_mp,
                          is_on_same_device, safe_ddp_context, show_layers, time_synchronize, torchacc_trim_graph,
                          use_torchacc)
from .utils import (add_version_to_work_dir, check_json_format, deep_getattr, get_pai_tensorboard_dir,
                    is_pai_training_job, lower_bound, parse_args, read_multi_line, seed_everything, subprocess_run,
                    test_time, upper_bound)
