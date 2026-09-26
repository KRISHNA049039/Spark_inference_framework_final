"""
triton_export.py - Build a Triton Inference Server model repository from the
platform's own models (TorchScript, PyTorch/libtorch backend), and verify a
running server returns the same numbers as eager PyTorch.

  # inside the multi-model-inference image
  python benchmark/triton_export.py --out /models                 # export
  python benchmark/triton_export.py --verify localhost:8001       # check server

Repository layout written (one directory per model):
  <out>/<model>/config.pbtxt
  <out>/<model>/1/model.pt
config: dynamic batching (requests from concurrent Spark tasks are merged up
to max_batch_size), 2 GPU instances of each model.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# model -> (sample shape, Triton max_batch_size, preferred batch sizes)
EXPORT = {
    "resnet18": ((3, 224, 224), 256, [64, 128, 256]),
    "ew_classifier": ((128,), 4096, [1024, 2048, 4096]),
}

CONFIG = """name: "{name}"
platform: "pytorch_libtorch"
max_batch_size: {mbs}
input [ {{ name: "INPUT__0" data_type: TYPE_FP32 dims: [ {in_dims} ] }} ]
output [ {{ name: "OUTPUT__0" data_type: TYPE_FP32 dims: [ {out_dims} ] }} ]
dynamic_batching {{
  preferred_batch_size: [ {pref} ]
  max_queue_delay_microseconds: 2000
}}
instance_group [ {{ count: 2 kind: KIND_GPU }} ]
"""


def export(out):
    import torch
    from models import get_default_registry
    reg = get_default_registry()
    report = {}
    for name, (shape, mbs, pref) in EXPORT.items():
        m = reg.load_model(name, device="cpu").eval()
        x = torch.randn(4, *shape)
        with torch.no_grad():
            ts = torch.jit.trace(m, x)
            ref, got = m(x), ts(x)
        d = os.path.join(out, name, "1")
        os.makedirs(d, exist_ok=True)
        ts.save(os.path.join(d, "model.pt"))
        out_dims = ", ".join(str(s) for s in ref.shape[1:])
        open(os.path.join(out, name, "config.pbtxt"), "w").write(CONFIG.format(
            name=name, mbs=mbs, in_dims=", ".join(map(str, shape)), out_dims=out_dims,
            pref=", ".join(map(str, pref))))
        report[name] = {"trace_max_abs_diff": float((ref - got).abs().max()), "output_dims": list(ref.shape[1:]),
                        "bytes": os.path.getsize(os.path.join(d, "model.pt"))}
        print(name, report[name])
    json.dump(report, open(os.path.join(out, "export_report.json"), "w"), indent=1)


def verify(url):
    import numpy as np
    import torch
    import tritonclient.grpc as grpcclient
    from models import get_default_registry
    reg = get_default_registry()
    c = grpcclient.InferenceServerClient(url=url)
    res = {"server": c.get_server_metadata(as_json=True)}
    for name, (shape, _, _) in EXPORT.items():
        m = reg.load_model(name, device="cpu").eval()
        x = np.random.randn(8, *shape).astype("float32")
        inp = grpcclient.InferInput("INPUT__0", list(x.shape), "FP32")
        inp.set_data_from_numpy(x)
        y = c.infer(name, [inp], outputs=[grpcclient.InferRequestedOutput("OUTPUT__0")]).as_numpy("OUTPUT__0")
        with torch.no_grad():
            ref = m(torch.from_numpy(x)).numpy()
        res[name] = {"max_abs_diff_vs_eager_cpu": float(np.abs(ref - y).max()),
                     "config": c.get_model_config(name, as_json=True)["config"]}
        print(name, "max |triton - eager| =", res[name]["max_abs_diff_vs_eager_cpu"])
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--verify")
    a = ap.parse_args()
    if a.out:
        export(a.out)
    if a.verify:
        verify(a.verify)
