# luts

胶片模拟 LUT（`*.cube`）。**因再分发许可不明确，`*.cube` 不入库。**

| 文件 | 说明 |
|------|------|
| `Portra160NC_c.cube` / `Portra160VC_c.cube` / `Fuji400H_c.cube` | 胶片模拟（G'MIC film emulation 系） |
| `kfinal_replica.cube` | 本项目内调校 |

获取：可用 G'MIC（gmic.eu）同源参数自行生成，或替换为任意 `.cube` —— 调色脚本 `tools/grade_demo.py` 接受任意 cube。

用法坑位：G'MIC 产出需洗掉 `DOMAIN_` 行；`ffmpeg lut3d` 在 LUT 所在目录用裸文件名调用最稳。
