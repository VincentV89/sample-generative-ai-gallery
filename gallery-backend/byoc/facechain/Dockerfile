# Base image
ARG ECR_REGISTRY
ARG ECR_REPOSITORY
ARG IMAGE_TAG
FROM ${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}

# Install necessary packages
RUN apt-get update && \
    apt-get install -y sudo wget git xz-utils nginx ca-certificates libsm6 libxext6 ffmpeg libfontconfig1 libxrender1 libgl1-mesa-glx && \
    rm -rf /var/lib/apt/lists/*

# Create new environment with specific Python version
RUN conda create -n py38 python=3.8.16 pip -y && \
    conda clean -ya

# Set PATH to use Python 3.8 by default
ENV PATH=/opt/conda/envs/py38/bin:$PATH

# Install dependencies using the Python 3.8 environment
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu117 && \
    pip install flask gevent gunicorn boto3 && \
    pip install mmcv-full -f https://download.openmmlab.com/mmcv/dist/cu117/torch2.0/index.html && \
    mkdir -p /opt/program/facefusion && \
    git clone https://github.com/raphael-shin/facechain.git /opt/program/facefusion && \
    cd /opt/program/facefusion && \
    pip install -r requirements.txt --no-cache-dir

# Bake the face fusion model into the image so endpoint start-up does not depend on the
# ModelScope hub (see download_model.py for why snapshot_download is not used)
ENV FACE_FUSION_MODEL_DIR=/opt/models/cv_unet_face_fusion_torch
ENV FACE_DETECTION_MODEL_DIR=/opt/models/cv_ddsar_face-detection_iclr23-damofd
COPY download_model.py /opt/download_model.py
RUN python /opt/download_model.py damo/cv_unet_face_fusion_torch v1.0.3 "$FACE_FUSION_MODEL_DIR" && \
    python /opt/download_model.py damo/cv_ddsar_face-detection_iclr23-damofd v1.1 "$FACE_DETECTION_MODEL_DIR" && \
    sed -i "s#det_model_id = 'damo/cv_ddsar_face-detection_iclr23-damofd'#det_model_id = '$FACE_DETECTION_MODEL_DIR'#" \
      "$FACE_FUSION_MODEL_DIR/ms_wrapper.py" && \
    grep -q "det_model_id = '$FACE_DETECTION_MODEL_DIR'" "$FACE_FUSION_MODEL_DIR/ms_wrapper.py"
# Fail the build (not the endpoint start-up) if the pipeline cannot be constructed. The build host
# has no GPU, so checkpoints saved on CUDA are mapped to the CPU for this check only.
RUN python -c "import os, functools, torch; \
    torch.load = functools.partial(torch.load, map_location='cpu'); \
    from modelscope.pipelines import pipeline; \
    pipeline('face_fusion_torch', model=os.environ['FACE_FUSION_MODEL_DIR']); print('face fusion pipeline OK')"

# Verify Python version
RUN echo "Python version:" && python --version && \
    echo "Python path:" && which python

# Set environment variables
ENV PYTHONUNBUFFERED=TRUE
ENV PYTHONDONTWRITEBYTECODE=TRUE
ENV PATH="/opt/program:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/opt/program/facefusion"

COPY src /opt/program
WORKDIR /opt/program

# Grant execution permissions to the script
RUN chmod +x /opt/program/serve

# SageMaker uses this port by default
EXPOSE 8080

# Set the entrypoint to run the serve script
ENTRYPOINT ["python", "/opt/program/serve"]