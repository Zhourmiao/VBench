"""VBench-2.0 Mechanics evaluation."""

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

from vbench2.utils import load_dimension_info

warnings.filterwarnings("ignore")


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


def llava_video(prompt_dict_ls, model, tokenizer, image_processor, device):
    final_score = 0
    valid_num = 0
    processed_json = []

    for prompt_dict in tqdm(prompt_dict_ls):
        base_questions = prompt_dict["auxiliary_info"]
        video_paths = prompt_dict["video_list"]

        for video_path in video_paths:
            # Reduced from 64 to limit peak VRAM usage on a 44 GB GPU.
            max_frames_num = 32
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
            )

            question_results = []
            answers = []

            for question_text in base_questions:
                question = (
                    DEFAULT_IMAGE_TOKEN
                    + time_instruction
                    + "Answer yes or no only for the following question.\n"
                    + question_text
                )

                conversation = copy.deepcopy(conv_templates["qwen_1_5"])
                conversation.append_message(
                    conversation.roles[0],
                    question,
                )
                conversation.append_message(
                    conversation.roles[1],
                    None,
                )

                prompt_question = conversation.get_prompt()
                input_ids = tokenizer_image_token(
                    prompt_question,
                    tokenizer,
                    IMAGE_TOKEN_INDEX,
                    return_tensors="pt",
                ).unsqueeze(0).to(device)

                with torch.inference_mode():
                    output_ids = model.generate(
                        input_ids,
                        images=video_input,
                        modalities=["video"],
                        do_sample=False,
                        temperature=0,
                        max_new_tokens=128,
                    )

                raw_answer = tokenizer.batch_decode(
                    output_ids,
                    skip_special_tokens=True,
                )[0].strip()
                answer = parse_yes_no(raw_answer)
                answers.append(answer)

                question_results.append(
                    {
                        "question": question_text,
                        "answer": answer,
                        "raw_answer": raw_answer,
                    }
                )

            # Mechanics uses the first question as a validity check in the
            # original VBench implementation. Invalid samples are excluded
            # from the aggregate score; valid samples pass only when all
            # remaining questions are yes.
            is_valid = bool(answers) and answers[0] == "yes"
            video_score = int(is_valid and all(
                answer == "yes" for answer in answers
            ))

            new_item = {
                "video_path": video_path,
                "video_results": video_score if is_valid else -1,
                "question_results": question_results,
            }
            processed_json.append(new_item)

            if is_valid:
                valid_num += 1
                final_score += video_score

    if valid_num == 0:
        raise RuntimeError("没有可用于 Mechanics 评测的有效视频")

    return final_score / valid_num, processed_json


def compute_mechanics(json_dir, device, submodules_dict, **kwargs):
    _, prompt_dict_ls = load_dimension_info(
        json_dir,
        dimension="mechanics",
        lang="en",
    )

    model_name = "llava_qwen"
    device_map = "auto"
    pretrained = submodules_dict["llava"]

    llava_tokenizer, llava_model, image_processor, _ = load_pretrained_model(
        pretrained,
        None,
        model_name,
        torch_dtype="bfloat16",
        device_map=device_map,
        # Avoid requiring flash-attn during debugging.
        attn_implementation="eager",
    )
    llava_model.eval()

    return llava_video(
        prompt_dict_ls,
        llava_model,
        llava_tokenizer,
        image_processor,
        device,
    )
