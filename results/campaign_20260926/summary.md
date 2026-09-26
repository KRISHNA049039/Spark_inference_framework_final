# Campaign summary

| test | aws_g4dn | windows | wsl2_docker |
|---|---|---|---|
| eng_rdd_cpu_only | **OK** Spark 4,192/s | **OK** Spark 952/s | **OK** Spark 2,578/s |
| eng_rdd_gpu_only | **OK** Spark 3,964/s | **OK** Spark 647/s | **OK** Spark 2,376/s |
| eng_udf_cpu_only | **OK** Spark 1,844/s | **OK** Spark 465/s | **OK** Spark 448/s |
| eng_udf_gpu_only | **OK** Spark 1,774/s | **OK** Spark 405/s | **OK** Spark 974/s |
| p1_dist_large | **OK** Spark 4,366/s | **OK** Spark 266/s | **OK** Spark 410/s |
| p1_modes_medium | **OK** Single 58,608/s, Hybrid 59,092/s, Spark 2,672/s | **PARTIAL** Single 19,609/s, Hybrid 6,765/s _(torch.load of truncated model bytes)_ | **OK** Single 8,278/s, Hybrid 542/s, Spark 75/s |
| p1_modes_small | **OK** Single 37,162/s, Hybrid 38,178/s, Spark 561/s | **PARTIAL** Single 9,681/s, Hybrid 13,745/s _(host RAM during CUDA JIT)_ | **OK** Single 2,680/s, Hybrid 8,605/s, Spark 80/s |
| p2_partitions_16 | **OK** Spark 1,699/s | **OK** Spark 144/s | **OK** Spark 429/s |
| p2_partitions_2 | **OK** Spark 2,454/s | **OK** Spark 529/s | **OK** Spark 342/s |
| p2_partitions_4 | **OK** Spark 2,667/s | **OK** Spark 307/s | **OK** Spark 538/s |
| p2_partitions_8 | **OK** Spark 2,320/s | **OK** Spark 204/s | **OK** Spark 356/s |
| p3_medium | **OK** Spark 2,677/s | **OK** Spark 328/s | **OK** Spark 436/s |
| p3_tiny | **OK** Spark 292/s | **OK** Spark 36/s | **OK** Spark 34/s |
| p3_xlarge | **OK** Spark 4,494/s | **OK** Spark 396/s | **OK** Spark 574/s |
| p4_batch_16 | **OK** Spark 2,569/s | **OK** Spark 388/s | **OK** Spark 464/s |
| p4_batch_256 | **OK** Spark 2,666/s | **OK** Spark 318/s | **OK** Spark 514/s |
| p4_batch_512 | **OK** Spark 2,645/s | **OK** Spark 399/s | **OK** Spark 375/s |
| p4_batch_64 | **OK** Spark 2,722/s | **OK** Spark 421/s | **OK** Spark 325/s |
| p7_cpu_only_medium | **OK** Spark 904/s | **OK** Spark 154/s | **OK** Spark 130/s |
| p7_cpu_only_small | **OK** Spark 416/s | **OK** Spark 111/s | **OK** Spark 54/s |
| p7_gpu_only_medium | **OK** Spark 1,444/s | **OK** Spark 192/s | **OK** Spark 126/s |
| p7_gpu_only_small | **OK** Spark 560/s | **OK** Spark 127/s | **OK** Spark 61/s |
| p7_hybrid_medium | **OK** Spark 1,449/s | **OK** Spark 181/s | **OK** Spark 131/s |
| p7_hybrid_small | **OK** Spark 569/s | **OK** Spark 130/s | **OK** Spark 45/s |
| p8_gpu_batch_128 | **OK** Spark 1,639/s | **FAIL**  _(host commit limit (JVM mmap failed))_ | **OK** Spark 137/s |
| p8_gpu_batch_32 | **OK** Spark 1,608/s | **OK** Spark 333/s | **OK** Spark 173/s |
| p8_gpu_batch_512 | **OK** Spark 1,619/s | **OK** Spark 325/s | **OK** Spark 237/s |
| svs_single_gpu | **OK** single_gpu_sequential 16,239/s, single_gpu_parallel_streams 58,842/s | **PARTIAL** single_gpu_sequential 4,142/s, single_gpu_parallel_streams 3,797/s _(host commit limit (JVM mmap failed))_ | **OK** single_gpu_sequential 1,404/s, single_gpu_parallel_streams 20,618/s |
