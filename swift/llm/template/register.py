# Copyright (c) Alibaba, Inc. and its affiliates.

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, Union

from transformers import PreTrainedTokenizerBase

from .base import Template
from .utils import Prompt, Word

TEMPLATE_MAPPING: Dict[str, Dict[str, Any]] = {}


@dataclass
class TemplateMeta:
    """
    Examples:
        chatml (with bos):
            prefix: <s>
            prompt: <|im_start|>user\n{{QUERY}}<|im_end|>\n<|im_start|>assistant\n
            chat_sep: <|im_end|>\n
            suffix: <|im_end|>
            system_prefix: <s><|im_start|>system\n{{SYSTEM}}<|im_end|>\n

        <s><|im_start|>system  # prefix or system_prefix
        {{SYSTEM}}<|im_end|>
        <|im_start|>user  # prompt
        {{QUERY}}<|im_end|>
        <|im_start|>assistant
        {{RESPONSE}}<|im_end|>  # chat_sep
        <|im_start|>user  # prompt
        {{QUERY}}<|im_end|>
        <|im_start|>assistant
        {{RESPONSE}}<|im_end|>  # suffix
    """
    template_type: str
    prefix: Prompt
    prompt: Prompt
    chat_sep: Optional[Prompt]
    suffix: Prompt
    template_cls: Type[Template] = Template
    tool_prompt: Optional[Prompt] = None
    system_prefix: Optional[Prompt] = None

    auto_add_bos: bool = False
    default_system: Optional[str] = None
    stop_words: List[Word] = field(default_factory=list)
    placeholder_tokens: List[Union[int, str]] = field(default_factory=list)
    skip_prompt: bool = True

    default_tools_prompt: str = 'react_en'
    support_stream: bool = True

    def to_generation_template_meta(self) -> 'TemplateMeta':
        return TemplateMeta(
            self.template_type,
            [],
            ['{{QUERY}}'],
            None,
            [['eos_token_id']],
            self.template_cls,
            auto_add_bos=True,
            stop_words=deepcopy(self.stop_words),
            placeholder_tokens=deepcopy(self.placeholder_tokens),
            skip_prompt=self.skip_prompt,
            support_stream=self.support_stream,
        )

    @staticmethod
    def _has_system(prefix_or_prompt: Prompt) -> bool:
        return any(['{{SYSTEM}}' in p for p in prefix_or_prompt])

    @staticmethod
    def _replace_system(prefix: Prompt) -> Prompt:
        """Replace system with the """
        return [p.replace('{{SYSTEM}}', '') for p in prefix]

    def _check_template_meta(self):
        # check
        for x in [self.prefix, self.prompt, self.suffix]:
            assert isinstance(x, list)
        for x in [self.chat_sep, self.system_prefix, self.tool_prompt]:
            assert x is None or isinstance(x, list)

    def __post_init__(self):
        # system
        if self._has_system(self.prefix):
            assert self.system_prefix is None, 'The prefix already contains {{SYSTEM}}.'
            self.system_prefix = self.prefix
            self.prefix = self._replace_system(self.prefix)

        self.is_post_system = self._has_system(self.prompt)  # mistral_nemo
        if self.is_post_system:
            self.prompt = [context for context in self.prompt if '{{SYSTEM}}' not in context]
            self.system_prompt = self.prompt

        if self.system_prefix is None and not self.is_post_system:
            self.support_system = False
        else:
            self.support_system = True
        self.default_system = self.check_system(self.default_system)

        self.support_multi_round = self.chat_sep is not None
        if self.tool_prompt is None:
            self.tool_prompt = self.prompt  # default as user

    @staticmethod
    def _token_attr_to_id(tokenizer: PreTrainedTokenizerBase, value: Optional[Prompt]) -> Optional[Prompt]:
        """Turn `eos_token_id` to token id

        e.g. [['eos_token_id']] -> [[2]]
        """
        if value is None:
            return None
        res_value = []
        for v in value:
            if isinstance(v, list):
                v = [getattr(tokenizer, sub_v) if isinstance(sub_v, str) else sub_v for sub_v in v]
            res_value.append(v)
        return res_value

    def token_attr_to_id(self, tokenizer: PreTrainedTokenizerBase) -> None:
        for key in ['prefix', 'prompt', 'chat_sep', 'suffix', 'system_prefix']:
            value = getattr(self, key)
            value = self._token_attr_to_id(tokenizer, value)
            setattr(self, key, value)

    def check_system(self, system: str) -> str:
        if system is None:
            system = ''
        if system:
            assert self.support_system, f'The template does not support `system`, template_type: {self.template_type}'
        return system


def register_template(template_meta: TemplateMeta, *, exist_ok: bool = False, **kwargs) -> None:
    template_type = template_meta.template_type
    if not exist_ok and template_type in TEMPLATE_MAPPING:
        raise ValueError(f'The `{template_type}` has already been registered in the TEMPLATE_MAPPING.')
    template_info = {'template_meta': template_meta, **kwargs}
    TEMPLATE_MAPPING[template_type] = template_info


def get_template(
        template_type: str,
        tokenizer: PreTrainedTokenizerBase,
        default_system: Optional[str] = None,
        max_length: Optional[int] = None,
        *,
        truncation_strategy: Literal['delete', 'truncation_left'] = 'delete',
        max_pixels: int = -1,  # h * w
        tools_prompt: str = 'react_en',
        # train
        loss_scale: str = 'default',
        sequence_parallel_size: int = 1) -> 'Template':
    template_info = TEMPLATE_MAPPING[template_type]
    # To ensure that obtaining the same template_type multiple times does not interfere with each other.
    template = deepcopy(template_info['template'])
    template._init_template(
        tokenizer,
        default_system,
        max_length,
        truncation_strategy=truncation_strategy,
        loss_scale=loss_scale,
        max_pixels=max_pixels,
        sequence_parallel_size=sequence_parallel_size,
        tools_prompt=tools_prompt)
    return template
