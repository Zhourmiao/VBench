#!/usr/bin/env bash

# Shared cache layout for all VBench evaluation processes.
# Source this file; do not execute it in a subshell.

export VBENCH_CACHE_ROOT="${VBENCH_CACHE_ROOT:-/root/.cache}"

# One shared Hugging Face cache.  LLaVA's SigLIP vision tower is stored here.
export HF_HOME="${VBENCH_HF_HOME:-$VBENCH_CACHE_ROOT/huggingface}"
export HF_DATASETS_CACHE="$HF_HOME/datasets"

# Benchmark-specific files are intentionally kept separate because the
# original VBench and VBench-2.0 code read different environment variables.
export VBENCH2_CACHE_DIR="$VBENCH_CACHE_ROOT/vbench2"
export VBENCH_CACHE_DIR="$VBENCH_CACHE_ROOT/vbench"

# Torch Hub paths follow the corresponding benchmark cache.  The active
# process sets TORCH_HOME to the benchmark it is running.
export VBENCH2_TORCH_HOME="$VBENCH2_CACHE_DIR/torch"
export VBENCH_TORCH_HOME="$VBENCH_CACHE_DIR/torch"
export TORCH_HOME="$VBENCH2_TORCH_HOME"

export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export NO_ALBUMENTATIONS_UPDATE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
