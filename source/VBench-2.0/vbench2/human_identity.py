"""VBench-2.0 Human Identity evaluation."""

import io
import os
import zipfile

import cv2
import decord
import numpy as np
import torch
from torch.utils import model_zoo
from tqdm import tqdm

from retinaface.predict_single import Model

from .third_party.arcface.models import resnet_face18
from vbench2.utils import load_dimension_info


def extract_face_features(face_image, model, device):
    face_image = cv2.resize(face_image, (128, 128))
    image_gray = cv2.cvtColor(face_image, cv2.COLOR_RGB2GRAY)
    image = np.dstack((image_gray, np.fliplr(image_gray)))
    image = image.transpose((2, 0, 1))
    image = image[:, np.newaxis, :, :].astype(np.float32, copy=False)
    image = (image - 127.5) / 127.5

    data = torch.from_numpy(image).to(device)
    with torch.inference_mode():
        output = model(data).detach().cpu().numpy()

    feature_1 = output[::2]
    feature_2 = output[1::2]
    return np.hstack((feature_1, feature_2)).flatten()


def calculate_similarity(x1, x2):
    denominator = np.linalg.norm(x1) * np.linalg.norm(x2)
    if denominator == 0:
        return 0.0
    return float(np.dot(x1, x2) / denominator)


class IDTracker:
    def __init__(self, similarity_threshold=0.4):
        self.reference_feature = None
        self.similarity_threshold = similarity_threshold

    def update(self, frame, frame_count, retina_model, arcface_model, device):
        frame = frame.astype(np.uint8)
        faces = retina_model.predict_jsons(frame)

        if faces is None or len(faces) != 1:
            return True, False

        box = faces[0].get("bbox")
        if box is None or len(box) != 4:
            return True, False

        x1, y1, x2, y2 = [int(value) for value in box]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(frame.shape[1], x2)
        y2 = min(frame.shape[0], y2)

        if x2 <= x1 or y2 <= y1:
            return True, False

        face_image = frame[y1:y2, x1:x2]
        feature = extract_face_features(
            face_image,
            arcface_model,
            device,
        )

        # The first sampled frame may not contain a detectable face. Use the
        # first valid face frame as the identity reference instead of relying
        # on the sampled frame index.
        if self.reference_feature is None:
            self.reference_feature = feature
            return True, True

        similarity = calculate_similarity(
            feature,
            self.reference_feature,
        )
        return similarity >= self.similarity_threshold, True


def evaluate_id_consistency(prompt_dict_ls, retina_model, arcface_model, device):
    total_consistent = 0
    total_valid = 0
    processed_json = []

    # Use enough frames for a stable identity estimate without loading the
    # complete video into GPU memory.
    max_sample_frames = 32
    minimum_valid_frames = 20

    for prompt_dict in tqdm(prompt_dict_ls):
        for video_path in prompt_dict["video_list"]:
            video_reader = decord.VideoReader(video_path)
            total_frames = len(video_reader)
            sample_count = min(max_sample_frames, total_frames)
            sample_indices = np.linspace(
                0,
                total_frames - 1,
                sample_count,
                dtype=int,
            ).tolist()
            frames = video_reader.get_batch(sample_indices).asnumpy()

            tracker = IDTracker(similarity_threshold=0.4)
            consistent_frame_count = 0
            valid_frame_count = 0

            for frame_count, frame in enumerate(frames):
                is_consistent, is_valid = tracker.update(
                    frame,
                    frame_count,
                    retina_model,
                    arcface_model,
                    device,
                )

                if not is_valid:
                    continue

                valid_frame_count += 1
                if is_consistent:
                    consistent_frame_count += 1

            item = {
                "video_path": video_path,
                "sampled_frames": sample_count,
                "valid_frames": valid_frame_count,
            }

            if valid_frame_count < minimum_valid_frames:
                item["video_results"] = -1
                item["invalid_reason"] = (
                    f"valid frames {valid_frame_count} < "
                    f"minimum {minimum_valid_frames}"
                )
            else:
                item["video_results"] = (
                    consistent_frame_count / valid_frame_count
                )
                total_consistent += consistent_frame_count
                total_valid += valid_frame_count

            processed_json.append(item)

    if total_valid == 0:
        return 0.0, processed_json

    return total_consistent / total_valid, processed_json


def load_arcface_model(checkpoint_path, device):
    model = resnet_face18(use_se=False)
    state_dict = torch.load(
        checkpoint_path,
        map_location="cpu",
    )
    cleaned_state_dict = {
        key.replace("module.", ""): value
        for key, value in state_dict.items()
    }
    model.load_state_dict(cleaned_state_dict)
    return model.to(device).eval()


def load_retinaface_checkpoint(checkpoint_path):
    """Load RetinaFace weights from either a torch file or the released zip."""
    if not zipfile.is_zipfile(checkpoint_path):
        return torch.load(checkpoint_path, map_location="cpu")

    with zipfile.ZipFile(checkpoint_path) as archive:
        candidates = [
            name for name in archive.namelist()
            if name.lower().endswith((".pth", ".pt", ".ckpt"))
        ]
        if not candidates:
            raise RuntimeError(
                f"No PyTorch checkpoint found inside RetinaFace archive: {checkpoint_path}"
            )
        with archive.open(candidates[0]) as handle:
            return torch.load(io.BytesIO(handle.read()), map_location="cpu")


def compute_human_identity(json_dir, device, submodules_dict, **kwargs):
    _, prompt_dict_ls = load_dimension_info(
        json_dir,
        dimension="human_identity",
        lang="en",
    )

    retina_filename = (
        "retinaface_resnet50_2020-07-20-f168fae3c.zip"
    )
    retina_url = (
        "https://github.com/ternaus/retinaface/releases/download/0.01/"
        + retina_filename
    )
    torch_home = os.environ.get(
        "TORCH_HOME",
        os.path.expanduser("~/.cache/torch"),
    )
    retina_candidates = [
        os.path.join(torch_home, "checkpoints", retina_filename),
        os.path.join(torch_home, "hub", "checkpoints", retina_filename),
    ]
    retina_checkpoint = next(
        (
            path for path in retina_candidates
            if os.path.isfile(path) and os.path.getsize(path) > 0
        ),
        None,
    )

    if retina_checkpoint is None:
        offline = os.environ.get("HF_HUB_OFFLINE") == "1"
        message = (
            "RetinaFace checkpoint not found or empty; checked: "
            + ", ".join(retina_candidates)
        )
        if offline:
            raise FileNotFoundError(
                message + "; HF_HUB_OFFLINE=1 prevents the fallback download"
            )
        print(message + "; downloading the checkpoint")
        retina_state_dict = model_zoo.load_url(
            retina_url,
            progress=True,
            map_location="cpu",
        )
    else:
        retina_state_dict = load_retinaface_checkpoint(retina_checkpoint)
    retina_model = Model(max_size=2048, device=device)
    retina_model.load_state_dict(retina_state_dict)

    arcface_checkpoint = submodules_dict["model"]
    if not os.path.isfile(arcface_checkpoint) or os.path.getsize(arcface_checkpoint) == 0:
        raise FileNotFoundError(f"ArcFace checkpoint not found or empty: {arcface_checkpoint}")
    arcface_model = load_arcface_model(arcface_checkpoint, device)

    return evaluate_id_consistency(
        prompt_dict_ls,
        retina_model,
        arcface_model,
        device,
    )
