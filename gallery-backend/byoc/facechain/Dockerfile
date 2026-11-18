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

# Bake the face fusion model weights into the image so endpoint start-up does not depend on
# downloading them from the ModelScope hub
ENV MODELSCOPE_CACHE=/opt/modelscope
# modelscope 1.8.x talks to the hub over plain http, which is reset outside mainland China; use https
RUN MS_CONST="$(python -c 'import modelscope.hub.constants as c; print(c.__file__)')" && \
    sed -i "s#MODELSCOPE_URL_SCHEME = 'http://'#MODELSCOPE_URL_SCHEME = 'https://'#" "$MS_CONST" && \
    grep -q "MODELSCOPE_URL_SCHEME = 'https://'" "$MS_CONST" && \
    for i in 1 2 3 4 5; do \
      python -c "from modelscope.hub.snapshot_download import snapshot_download; print(snapshot_download('damo/cv_unet_face_fusion_torch', revision='v1.0.3'))" && break; \
      [ $i -lt 5 ] && sleep 20 || exit 1; \
    done

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