# Spark execution modes - statistics

| model | mode | samples/s | wall s | jobs | stages | tasks | executors (host: tasks) | model loads | GPU SM % avg |
|---|---|---|---|---|---|---|---|---|---|
| ew_classifier | rdd_cpu | 120.1 | 16.648 | 1 | 1 | 4 | ad59867d3a7f:4 | 4 | - |
| ew_classifier | rdd_hybrid | 103.4 | 19.333 | 1 | 1 | 4 | ad59867d3a7f:4 | 4 | - |
| ew_classifier | udf_gpu | 50.5 | 39.609 | 2 | 2 | 6 | ad59867d3a7f:6 | 0 | - |
| ew_classifier | native_pbu_gpu | 58.5 | 34.169 | 2 | 2 | 6 | ad59867d3a7f:6 | 1 | - |
| resnet18 | rdd_cpu | 0.1 | 59.525 | 1 | 1 | 4 | ad59867d3a7f:4 | 4 | - |
| resnet18 | rdd_hybrid | 0.1 | 53.605 | 1 | 1 | 4 | ad59867d3a7f:4 | 4 | - |
| resnet18 | udf_gpu | 0.1 | 87.816 | 2 | 2 | 6 | ad59867d3a7f:6 | 0 | - |
| resnet18 | native_pbu_gpu | 0.1 | 61.913 | 2 | 2 | 6 | ad59867d3a7f:6 | 1 | - |
