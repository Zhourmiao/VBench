"""VBench-2.0 Motion Order Understanding evaluation."""

import copy
import re
import warnings

import numpy as np
import torch
from decord import VideoReader, cpu
from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX
from llava.conversation import conv_templates
from llava.mm_utils import tokenizer_image_token
from llava.model.builder import load_pretrained_model
from tqdm import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer

from vbench2.utils import load_dimension_info

warnings.filterwarnings("ignore")


SYS_PROMPT = """You are Qwen, created by Alibaba Cloud. You are a helpful assistant and a brilliant action order judger.
You need to judge the consistency of the action in two given prompts. Focus only on the action; similar semantic expressions should be considered consistent.
Do not make associations. The action should actually have happened. Answer yes or no first, then give the reason.
"""


def load_video(video_path, max_frames_num, fps=1, force_sample=False):
    if max_frames_num == 0:
        return np.zeros((1, 336, 336, 3))

    vr = VideoReader(video_path, ctx=cpu(0), num_threads=1)
    total_frame_num = len(vr)
    video_time = total_frame_num / vr.get_avg_fps()

    sample_step = max(round(vr.get_avg_fps() / fps), 1)
    frame_idx = list(range(0, total_frame_num, sample_step))
    frame_time = [i / vr.get_avg_fps() for i in frame_idx]

    if len(frame_idx) > max_frames_num or force_sample:
        sample_frame_count = min(max_frames_num, total_frame_num)
        uniform_indices = np.linspace(
            0,
            total_frame_num - 1,
            sample_frame_count,
            dtype=int,
        )
        frame_idx = uniform_indices.tolist()
        frame_time = [i / vr.get_avg_fps() for i in frame_idx]

    frame_time_text = ",".join(f"{i:.2f}s" for i in frame_time)
    video = vr.get_batch(frame_idx).asnumpy()
    return video, frame_time_text, video_time


def parse_yes_no(raw_answer):
    match = re.search(r"\b(yes|no)\b", raw_answer.lower())
    return match.group(1) if match else "unknown"


def judge(prompt, model, tokenizer):
    messages = [
        {"role": "system", "content": SYS_PROMPT},
        {"role": "user", "content": prompt},
    ]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    model_inputs = tokenizer(
        [text],
        return_tensors="pt",
    ).to(model.device)

    with torch.inference_mode():
        generated_ids = model.generate(
            **model_inputs,
            do_sample=False,
            temperature=0,
            max_new_tokens=128,
        )

    generated_ids = [
        output_ids[len(input_ids):]
        for input_ids, output_ids in zip(
            model_inputs.input_ids,
            generated_ids,
        )
    ]
    return tokenizer.batch_decode(
        generated_ids,
        skip_special_tokens=True,
    )[0].strip()


def split_by_numbered_list(text):
    parts = re.split(r"\d+\.\s*", text)
    return [part.strip() for part in parts if part.strip()]


def llava_video(
    prompt_dict_ls,
    llava_model,
    llava_tokenizer,
    image_processor,
    qwen_model,
    qwen_tokenizer,
    device,
):
    final_score = 0
    valid_num = 0
    processed_json = []

    for prompt_dict in tqdm(prompt_dict_ls):
        video_paths = prompt_dict["video_list"]
        ground_truth_text = prompt_dict["auxiliary_info"]

        for video_path in video_paths:
            # Reduced from 64 to limit peak VRAM usage on a 44 GB GPU.
            max_frames_num = 16
            video, frame_time, video_time = load_video(
                video_path,
                max_frames_num=max_frames_num,
                fps=1,
                force_sample=True,
            )

            pixel_values = image_processor.preprocess(
                video,
                return_tensors="pt",
            )["pixel_values"].to(device).bfloat16()
            video_input = [pixel_values]

            time_instruction = (
                f"The video lasts for {video_time:.2f} seconds, "
                f"and {len(video_input[0])} frames are uniformly sampled "
                f"from it. These frames are located at {frame_time}. "
                "Return the action order in the video. Use exactly this format:"
            )
            question = (
                DEFAULT_IMAGE_TOKEN
                + time_instruction
                + "\n1. ; 2. ."
            )

            conversation = copy.deepcopy(conv_templates["qwen_1_5"])
            conversation.append_message(conversation.roles[0], question)
            conversation.append_message(conversation.roles[1], None)
            prompt_question = conversation.get_prompt()

            input_ids = tokenizer_image_token(
                prompt_question,
                llava_tokenizer,
                IMAGE_TOKEN_INDEX,
                return_tensors="pt",
            ).unsqueeze(0).to(device)

            with torch.inference_mode():
                output_ids = llava_model.generate(
                    input_ids,
                    images=video_input,
                    modalities=["video"],
                    do_sample=False,
                    temperature=0,
                    max_new_tokens=128,
                )

            # Different LLaVA versions return either prompt+completion or
            # completion-only token ids. Prefer the completion slice, but
            # fall back to the full output when that slice is empty.
            generated_ids = output_ids[:, input_ids.shape[1]:]
            llava_answer = llava_tokenizer.batch_decode(
                generated_ids,
                skip_special_tokens=True,
            )[0].strip()

            if not llava_answer:
                llava_answer = llava_tokenizer.batch_decode(
                    output_ids,
                    skip_special_tokens=True,
                )[0].strip()

            # If the full prompt is included, keep the final numbered list
            # rather than the example template in the user prompt.
            numbered_starts = list(
                re.finditer(r"(?m)^\s*1\.\s*", llava_answer)
            )
            if numbered_starts:
                llava_answer = llava_answer[numbered_starts[-1].start():]
            action_parts = split_by_numbered_list(llava_answer)

            new_item = {
                "video_path": video_path,
                "llava_answer": llava_answer,
                "qwen_results": [],
            }

            if len(action_parts) < 2 or len(ground_truth_text) < 2:
                new_item["video_results"] = -1
                new_item["invalid_reason"] = (
                    "LLaVA did not return two numbered action descriptions"
                )
                print(
                    f"[Motion_Order_Understanding] invalid LLaVA output "
                    f"for {video_path}: {llava_answer!r}"
                )
                processed_json.append(new_item)
                continue

            score = 0
            for index in range(2):
                prompt = (
                    f"prompt1: {ground_truth_text[index]}\n"
                    f"prompt2: {action_parts[index]}"
                )
                raw_response = judge(
                    prompt,
                    qwen_model,
                    qwen_tokenizer,
                )
                answer = parse_yes_no(raw_response)

                if answer == "yes":
                    score += 1

                new_item["qwen_results"].append(
                    {
                        "prompt1": ground_truth_text[index],
                        "prompt2": action_parts[index],
                        "answer": answer,
                        "raw_answer": raw_response,
                    }
                )

            video_score = int(score == 2)
            new_item["video_results"] = video_score
            final_score += video_score
            valid_num += 1
            processed_json.append(new_item)

    if valid_num == 0:
        print(
            "[Motion_Order_Understanding] 没有可用于 Qwen 判断的有效视频；"
            "已保存每个视频的 LLaVA 原始输出，便于排查格式问题。"
        )
        return 0.0, processed_json

    return final_score / valid_num, processed_json


def compute_motion_order_understanding(
    json_dir,
    device,
    submodules_dict,
    **kwargs,
):
    _, prompt_dict_ls = load_dimension_info(
        json_dir,
        dimension="motion_order_understanding",
        lang="en",
    )

    llava_tokenizer, llava_model, image_processor, _ = load_pretrained_model(
        submodules_dict["llava"],
        None,
        "llava_qwen",
        torch_dtype="bfloat16",
        device_map="auto",
        attn_implementation="eager",
    )
    llava_model.eval()

    qwen_model = AutoModelForCausalLM.from_pretrained(
        submodules_dict["qwen"],
        torch_dtype="auto",
        device_map="auto",
        local_files_only=True,
    )
    qwen_tokenizer = AutoTokenizer.from_pretrained(
        submodules_dict["qwen"],
        local_files_only=True,
    )
    qwen_model.eval()

    return llava_video(
        prompt_dict_ls,
        llava_model,
        llava_tokenizer,
        image_processor,
        qwen_model,
        qwen_tokenizer,
        device,
    )
