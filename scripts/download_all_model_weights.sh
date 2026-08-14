#!/usr/bin/env bash
set -Eeuo pipefail

# Download the public VBench/VBench-2.0 evaluation weights.
# The directory layout matches scripts/vbench_env.sh and pipelines/core/check_models.py.
# Override VBENCH_CACHE_ROOT and HF_HOME when the target server uses another disk.

CACHE_ROOT="${VBENCH_CACHE_ROOT:-${HOME:-/root}/.cache}"
VBENCH_CACHE="${VBENCH_CACHE_DIR:-$CACHE_ROOT/vbench}"
VBENCH2_CACHE="${VBENCH2_CACHE_DIR:-$CACHE_ROOT/vbench2}"
HF_HOME="${HF_HOME:-$CACHE_ROOT/huggingface}"

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }

download_file() {
    local url="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if [[ -s "$dest" ]]; then
        log "跳过已存在文件: $dest"
        return
    fi
    log "下载: $dest"
    curl -fL --retry 5 --retry-all-errors -C - "$url" -o "$dest"
}

download_gdrive() {
    local file_id="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if [[ -s "$dest" ]]; then
        log "跳过已存在文件: $dest"
        return
    fi
    command -v gdown >/dev/null 2>&1 || {
        echo "缺少 gdown，请先安装: pip install gdown" >&2
        return 1
    }
    log "下载 Google Drive 权重: $dest"
    gdown --id "$file_id" -O "$dest"
}

download_gdrive_folder() {
    local url="$1" dest="$2"
    if [[ -n "$(find "$dest" -type f -size +1k 2>/dev/null | head -1)" ]]; then
        log "跳过已存在目录: $dest"
        return
    fi
    command -v gdown >/dev/null 2>&1 || {
        echo "缺少 gdown，请先安装: pip install gdown" >&2
        return 1
    }
    mkdir -p "$dest"
    log "下载 Google Drive 模型目录: $dest"
    gdown --folder "$url" -O "$dest"
}

download_hf_repo() {
    local repo="$1"
    if command -v hf >/dev/null 2>&1; then
        log "下载 Hugging Face: $repo"
        hf download "$repo" --cache-dir "$HF_HOME"
    elif command -v huggingface-cli >/dev/null 2>&1; then
        log "下载 Hugging Face: $repo"
        huggingface-cli download "$repo" --cache-dir "$HF_HOME"
    else
        echo "缺少 hf/huggingface-cli，请先安装: pip install -U huggingface_hub" >&2
        return 1
    fi
}

download_raft() {
    local cache="$1"
    local model_dir="$cache/raft_model/models"
    if [[ -s "$model_dir/raft-things.pth" ]]; then
        log "跳过已存在 RAFT 权重"
        return
    fi
    mkdir -p "$cache/raft_model"
    local archive="$cache/raft_model/models.zip"
    download_file \
        "https://dl.dropboxusercontent.com/s/4j4z58wuv8o0mfz/models.zip" \
        "$archive"
    command -v unzip >/dev/null 2>&1 || {
        echo "缺少 unzip，请先安装系统包 unzip" >&2
        return 1
    }
    unzip -o "$archive" -d "$cache/raft_model"
    rm -f "$archive"
}

download_dreamsim() {
    local cache="$1/dreamsim_ckpts"
    if [[ -n "$(find "$cache" -type f -size +1k 2>/dev/null | head -1)" ]]; then
        log "跳过已存在 DreamSim 权重"
        return
    fi
    mkdir -p "$cache"
    command -v python >/dev/null 2>&1 || {
        echo "缺少 python，无法触发 DreamSim 权重下载" >&2
        return 1
    }
    log "通过 DreamSim Python API 下载权重"
    DREAMSIM_CACHE_DIR="$cache" python - <<'PY'
import os
from dreamsim import dreamsim

dreamsim(pretrained=True, device="cpu", cache_dir=os.environ["DREAMSIM_CACHE_DIR"])
print("DreamSim download completed")
PY
}

download_vbench() {
    log "开始下载 VBench 权重到 $VBENCH_CACHE"

    download_file \
        "https://dl.fbaipublicfiles.com/dino/dino_vitbase16_pretrain/dino_vitbase16_pretrain.pth" \
        "$VBENCH_CACHE/dino_model/dino_vitbase16_pretrain.pth"

    if [[ ! -d "$VBENCH_CACHE/dino_model/facebookresearch_dino_main/.git" ]]; then
        log "下载 DINO 代码仓库"
        git clone --depth 1 https://github.com/facebookresearch/dino \
            "$VBENCH_CACHE/dino_model/facebookresearch_dino_main"
    fi

    download_file \
        "https://openaipublic.azureedge.net/clip/models/40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt" \
        "$VBENCH_CACHE/clip_model/ViT-B-32.pt"
    download_file \
        "https://openaipublic.azureedge.net/clip/models/b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836/ViT-L-14.pt" \
        "$VBENCH_CACHE/clip_model/ViT-L-14.pt"
    download_file \
        "https://raw.githubusercontent.com/LAION-AI/aesthetic-predictor/main/sa_0_4_vit_l_14_linear.pth" \
        "$VBENCH_CACHE/aesthetic_model/emb_reader/sa_0_4_vit_l_14_linear.pth"
    download_file \
        "https://huggingface.co/lalala125/AMT/resolve/main/amt-s.pth" \
        "$VBENCH_CACHE/amt_model/amt-s.pth"
    download_file \
        "https://huggingface.co/spaces/xinyu1205/recognize-anything/resolve/main/tag2text_swin_14m.pth" \
        "$VBENCH_CACHE/caption_model/tag2text_swin_14m.pth"
    download_file \
        "https://huggingface.co/OpenGVLab/VBench_Used_Models/resolve/main/grit_b_densecap_objectdet.pth" \
        "$VBENCH_CACHE/grit_model/grit_b_densecap_objectdet.pth"
    download_file \
        "https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/musiq_spaq_ckpt-358bb6af.pth" \
        "$VBENCH_CACHE/pyiqa_model/musiq_spaq_ckpt-358bb6af.pth"
    download_file \
        "https://huggingface.co/OpenGVLab/VBench_Used_Models/resolve/main/l16_ptk710_ftk710_ftk400_f16_res224.pth" \
        "$VBENCH_CACHE/umt_model/l16_ptk710_ftk710_ftk400_f16_res224.pth"
    download_file \
        "https://huggingface.co/OpenGVLab/VBench_Used_Models/resolve/main/ViClip-InternVid-10M-FLT.pth" \
        "$VBENCH_CACHE/ViCLIP/ViClip-InternVid-10M-FLT.pth"
    download_file \
        "https://huggingface.co/facebook/cotracker/resolve/main/cotracker2.pth" \
        "$VBENCH_CACHE/torch/hub/checkpoints/cotracker2.pth"
    download_raft "$VBENCH_CACHE"
    download_dreamsim "$VBENCH_CACHE"
}

download_vbench2() {
    log "开始下载 VBench-2.0 权重到 $VBENCH2_CACHE"

    download_hf_repo "lmms-lab/LLaVA-Video-7B-Qwen2"
    download_hf_repo "Qwen/Qwen2.5-7B-Instruct"
    download_hf_repo "google/siglip-so400m-patch14-384"
    download_gdrive "1m387vGTQ4GW4I4PQfBsCC-Y9aEp6zjvy" \
        "$VBENCH2_CACHE/arcface/resnet18_110.pth"
    download_file \
        "https://github.com/ternaus/retinaface/releases/download/0.01/retinaface_resnet50_2020-07-20-f168fae3c.zip" \
        "$VBENCH2_CACHE/torch/checkpoints/retinaface_resnet50_2020-07-20-f168fae3c.zip"
    download_file \
        "https://huggingface.co/facebook/cotracker/resolve/main/cotracker2.pth" \
        "$VBENCH2_CACHE/torch/hub/checkpoints/cotracker2.pth"
    download_raft "$VBENCH2_CACHE"

    download_gdrive "1qo-K1kum7yiEwIlN1TWDvABXX6qriUen" \
        "$VBENCH2_CACHE/YOLO-World/yolo_world_v2_xl_obj365v1_goldg_cc3mlite_pretrain-5daf1395.pth"
    download_gdrive "1mlSURYOi_vN9ST1wzEhJaVO6-ZoES8UT" \
        "$VBENCH2_CACHE/anomaly_detector/human.pth"
    download_gdrive "1e2qTjrtsYlkWLql0qj8DqaNZ09KuV8Qo" \
        "$VBENCH2_CACHE/anomaly_detector/face.pth"
    download_gdrive "1j3QeAcAtdLe5BFgK-c33UaHV6-iUto0i" \
        "$VBENCH2_CACHE/anomaly_detector/hand.pth"
    download_gdrive_folder \
        "https://drive.google.com/drive/folders/106rnzZvH-VUKkz8dMPFflD6tqtbSgXwh" \
        "$VBENCH2_CACHE/instance_anomaly_detector"
}

scope="all"
if [[ "${1:-}" == "--vbench" ]]; then
    scope="vbench"
elif [[ "${1:-}" == "--vbench2" ]]; then
    scope="vbench2"
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
用法:
  ./scripts/download_all_model_weights.sh          下载 VBench 和 VBench-2.0 全部权重
  ./scripts/download_all_model_weights.sh --vbench 只下载 VBench 权重
  ./scripts/download_all_model_weights.sh --vbench2 只下载 VBench-2.0 权重

环境变量:
  VBENCH_CACHE_ROOT  默认 $HOME/.cache（容器中通常是 /root/.cache）
  VBENCH_CACHE_DIR   默认 $VBENCH_CACHE_ROOT/vbench
  VBENCH2_CACHE_DIR  默认 $VBENCH_CACHE_ROOT/vbench2
  HF_HOME            默认 $VBENCH_CACHE_ROOT/huggingface
EOF
    exit 0
else
    [[ -z "${1:-}" ]] || { echo "未知参数: $1" >&2; exit 2; }
fi

mkdir -p "$VBENCH_CACHE" "$VBENCH2_CACHE" "$HF_HOME"

case "$scope" in
    vbench) download_vbench ;;
    vbench2) download_vbench2 ;;
    all) download_vbench; download_vbench2 ;;
esac

log "下载完成。建议执行模型检查:"
printf '  VBENCH_CACHE_DIR=%q python pipelines/core/check_models.py --benchmark vbench_i2v --dimensions i2v_subject i2v_background background_consistency aesthetic_quality imaging_quality motion_smoothness dynamic_degree camera_motion\n' "$VBENCH_CACHE"
printf '  VBENCH2_CACHE_DIR=%q HF_HOME=%q python pipelines/core/check_models.py --benchmark vbench2 --dimensions Motion_Rationality Human_Identity Multi-View_Consistency\n' "$VBENCH2_CACHE" "$HF_HOME"
