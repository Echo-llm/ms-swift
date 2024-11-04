# Copyright (c) Alibaba, Inc. and its affiliates.
# Classification criteria for model_type: same model architecture, tokenizer (get function), template.
from typing import List


class LLMModelType:
    # dense
    qwen = 'qwen'
    codefuse_qwen = 'codefuse_qwen'
    modelscope_agent = 'modelscope_agent'
    qwen2 = 'qwen2'
    qwen2_5 = 'qwen2_5'

    llama = 'llama'
    llama3 = 'llama3'
    longwriter_llama3 = 'longwriter_llama3'
    llama3_2 = 'llama3_2'
    yi = 'yi'
    yi_coder = 'yi_coder'

    reflection_llama3_1 = 'reflection_llama3_1'

    chatglm2 = 'chatglm2'
    chatglm3 = 'chatglm3'
    codefuse_codegeex2 = 'codefuse_codegeex2'
    codegeex4 = 'codegeex4'
    glm4 = 'glm4'

    internlm = 'internlm'
    internlm2 = 'internlm2'

    longwriter_llama3_1 = 'longwriter_llama3_1'
    longwriter_glm4 = 'longwriter_glm4'

    atom = 'atom'

    # moe
    qwen2_moe = 'qwen2_moe'


class MLLMModelType:
    qwen_vl = 'qwen_vl'
    qwen_audio = 'qwen_audio'
    qwen2_vl = 'qwen2_vl'
    qwen2_audio = 'qwen2_audio'
    llama3_2_vision = 'llama3_2_vision'

    glm4v = 'glm4v'
    cogvlm = 'cogvlm'
    cogagent_vqa = 'cogagent_vqa'
    cogagent_chat = 'cogagent_chat'
    cogvlm2 = 'cogvlm2'
    cogvlm2_video = 'cogvlm2_video'

    xcomposer2 = 'xcomposer2'
    xcomposer2_4khd = 'xcomposer2_4khd'
    xcomposer2_5 = 'xcomposer2_5'

    llama3_1_omni = 'llama3_1_omni'
    idefics3_llama3 = 'idefics3_llama3'

    llava1_5 = 'llava1_5'
    llava1_6_mistral = 'llava1_6_mistral'
    llava1_6_vicuna = 'llava1_6_vicuna'
    llava1_6_yi = 'llava1_6_yi'
    llava1_6_llama3_1 = 'llava1_6_llama3_1'
    llava_next = 'llava_next'


class ModelType(LLMModelType, MLLMModelType):

    @classmethod
    def get_model_name_list(cls) -> List[str]:
        res = []
        for k in cls.__dict__.keys():
            if k.startswith('__'):
                continue
            value = cls.__dict__[k]
            if isinstance(value, str):
                res.append(value)
        return res
