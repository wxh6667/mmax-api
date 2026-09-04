"""本项目针对第三方/ComfyUI checkpoint 的 state-dict 兼容转换器。"""


def Krea2ComfyTextEncoderStateDictConverter(state_dict):
    """兼容 ComfyUI 打包的 Qwen3-VL 文本编码器。

    官方 Qwen3-VL checkpoint 使用 ``model.language_model.*``，而部分 ComfyUI
    文本编码器会裁掉 ``language_model`` 这一层，保存成 ``model.layers.*``、
    ``model.embed_tokens.*``、``model.norm.*``。DiffSynth 官方 Krea2 converter
    只识别前一种格式，因此这里先恢复官方层级，再交给官方 converter 处理。
    """
    normalized = {}

    for key in state_dict:
        value = state_dict[key]

        if key.startswith("model.language_model."):
            # 已经是官方 Qwen3-VL 文本分支命名，保持不变。
            new_key = key
        elif key.startswith("model.visual."):
            # 已经是官方视觉分支命名，保持不变。
            new_key = key
        elif key.startswith("visual."):
            # 少数打包格式可能同时裁掉最外层 model。
            new_key = "model." + key
        elif key.startswith("model."):
            # ComfyUI 文本编码器常见格式：model.layers.* / model.embed_tokens.*
            new_key = "model.language_model." + key[len("model."):]
        elif key.startswith("lm_head."):
            new_key = "model." + key
        else:
            new_key = key

        normalized[new_key] = value

    from diffsynth.utils.state_dict_converters.krea2_text_encoder import (
        Krea2TextEncoderStateDictConverter,
    )

    return Krea2TextEncoderStateDictConverter(normalized)
