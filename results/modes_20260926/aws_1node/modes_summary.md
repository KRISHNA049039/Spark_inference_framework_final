# Spark execution modes - statistics

| model | mode | samples/s | wall s | jobs | stages | tasks | executors (host: tasks) | model loads | GPU SM % avg |
|---|---|---|---|---|---|---|---|---|---|
| example_mlp | rdd_cpu | 4191.9 | 4.7711 | 1 | 1 | 4 | 10.0.0.240:4 | 4 | - |
| example_mlp | rdd_gpu | 3964.2 | 5.0452 | 1 | 1 | 4 | 10.0.0.240:4 | 4 | - |
| example_mlp | udf_cpu | 1844.2 | 10.8447 | 2 | 2 | 6 | 10.0.0.240:6 | 0 | - |
| example_mlp | udf_gpu | 1774.3 | 11.272 | 2 | 2 | 6 | 10.0.0.240:6 | 0 | - |
| platform10_1k | rdd_cpu | 416.0 | 12.48 | 1 | 1 | 2 | 10.0.0.240:2 | 2 | - |
| platform10_1k | rdd_gpu | 560.0 | 9.26 | 1 | 1 | 2 | 10.0.0.240:2 | 2 | - |
| platform10_1k | rdd_hybrid | 569.0 | 9.13 | 1 | 1 | 2 | 10.0.0.240:2 | 2 | - |
| platform10_3k | rdd_cpu | 904.0 | 16.98 | 1 | 1 | 4 | 10.0.0.240:4 | 4 | - |
| platform10_3k | rdd_gpu | 1444.0 | 10.63 | 1 | 1 | 4 | 10.0.0.240:4 | 4 | - |
| platform10_3k | rdd_hybrid | 1449.0 | 10.6 | 1 | 1 | 4 | 10.0.0.240:4 | 4 | - |
| platform10_5k | dist_p2 | 2454.0 | 10.26 | 1 | 1 | 2 | 10.0.0.240:2 | 0 | - |
| platform10_5k | dist_p4 | 2667.0 | 9.44 | 1 | 1 | 4 | 10.0.0.240:4 | 0 | - |
| platform10_5k | dist_p8 | 2320.0 | 10.85 | 1 | 1 | 8 | 10.0.0.240:8 | 0 | - |
| platform10_5k | dist_p16 | 1699.0 | 14.81 | 1 | 1 | 16 | 10.0.0.240:16 | 0 | - |
