# Fallback llama-swap + llama.cpp image built specifically for the Tesla P4 (Pascal, sm_61) on CUDA 12.4.
# Needed if the prebuilt ghcr.io/mostlygeek/llama-swap:cuda image can't see the GPU
# (e.g. driver < 570 can't run CUDA 12.8). Building on an i5-8500T takes ~20–40 minutes.
#   In .env: LLM_IMAGE=notes-llm:pascal
#   docker build -t notes-llm:pascal llm/ && docker compose up -d llm   (scripts/check-gpu.sh does the build)
ARG CUDA_VERSION=12.4.1
ARG UBUNTU_VERSION=22.04

FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS build
# llama.cpp tag/commit (b-number release). master = latest; better to pin a tested one.
ARG LLAMA_CPP_REF=master
RUN apt-get update && apt-get install -y --no-install-recommends git cmake build-essential ca-certificates libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${LLAMA_CPP_REF} https://github.com/ggml-org/llama.cpp /src
WORKDIR /src
RUN cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61 -DGGML_NATIVE=OFF \
      -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_CURL=OFF \
      -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined \
    && cmake --build build --config Release -j"$(nproc)" --target llama-server \
    && mkdir -p /out && cp build/bin/llama-server /out/ && find build -name '*.so*' -exec cp -P {} /out/ \;

FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}
ARG LS_VER=262
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /out/ /app/
RUN curl -fL "https://github.com/mostlygeek/llama-swap/releases/download/v${LS_VER}/llama-swap_${LS_VER}_linux_amd64.tar.gz" \
      | tar -xz -C /app && chmod -R a+rX /app
ENV PATH="/app:${PATH}" LD_LIBRARY_PATH="/app:${LD_LIBRARY_PATH}"
HEALTHCHECK CMD curl -f http://localhost:8080/ || exit 1
ENTRYPOINT ["/app/llama-swap", "-config", "/app/config.yaml", "-watch-config"]
