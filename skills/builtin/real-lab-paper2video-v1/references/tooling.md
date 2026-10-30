# 工程工具

以下 `<skill>` 使用本技能实际目录，`<project>` 使用 `outputs/<论文简称>/assets/paper-video` 的实际路径。从 Easel 项目根执行，Python 使用 `.venv/bin/python`。工作工程与中间文件留在 assets，最终视频、字幕、讲稿和封面交付到 `outputs/<论文简称>/`。

## 初始化与依赖

```bash
python <skill>/scripts/easel_video.py init <project>
```

选择一个新目录。初始化器复制8秒演示工程、渲染/验证脚本和内置资产模块。依据选定的开场形式与镜头表编辑页面DOM、文案、图资产与动画，将同一总时长写入 `project.json` 和 `timeline.js`，然后设置 `demo:false`。

使用当前可用的Node.js、Playwright、Chrome、FFmpeg/FFprobe。Python验证需要NumPy和Pillow，资产提取依赖见[内置资产模块](paper-assets.md)。需要补依赖时安装到项目或隔离环境。Easel 入口优先复用 Python Playwright 内置模块，也可通过 `PLAYWRIGHT_MODULE` 指定已有模块目录，`BROWSER_CHANNEL` 默认 `chrome`。

模板采用1920×1080设计坐标。改变画幅时同步调整CSS、SVG viewBox、缩放方式和字幕安全区。已有工程可沿用其结构，接入需要的助手和规范。

在 `index.html` 的CSS `:root` 中设置 `--bg`、`--ink`、`--accent`、`--muted`、`--line`、`--node-fill` 与 `--diagram-muted`，统一控制HTML和SVG配色。`--highlight` 默认跟随强调色，可根据论文原图的局部对比单独设置。图像衬边保持白色。

## 时间驱动渲染

页面提供 `window.render(t)`，在字体和图片decode完成后设置 `window.ready=true`。将位置、透明度、路径和强调状态直接写成时间t的函数；随机效果使用固定种子。任意跳时后重渲同一帧应得到一致画面。

```bash
python <skill>/scripts/easel_video.py render <project> <project>/qa/opening-v1.png --still-frame 90
python <skill>/scripts/easel_video.py render <project> <project>/renders/preview-v1.mp4 --start-frame 0 --end-frame 180 --scale 0.6666666667
python <skill>/scripts/easel_video.py render <project> <project>/renders/visual-v1.mp4
```

演示工程试跑加 `--allow-demo`。修订使用新输出文件名；原位重建可加 `--overwrite`。渲染器先写临时文件，成功后替换目标。

静帧和片段使用全局整数帧时间 `n/fps`，片段范围为 `[startFrame,endFrame)`。随文件输出的 `.render.json` 记录参数、帧范围和入口文件哈希。分段缓存按[制作流程](production.md)记录完整输入。

整片可一次编码；并行渲染时划分不相交的整数帧区间，所有分段使用相同编码参数。concat清单为每段写入 `duration=frameCount/fps`，再验最终帧数与PTS。

## 框选和转场助手

- `Motion.mapHighlight([X,Y,W,H],[sourceW,sourceH],[x,y,w,h],22)`：将源图矩形换算到含白边与contain留空的画面坐标。将返回值赋给与图片同层的 `.paper-highlight`。
- `Motion.validateCues(cues)`：检查框选时间区间的顺序与互斥。
- `Motion.cueOpacity(t,start,end)`：生成框选淡入淡出透明度。
- `Motion.transition(t,boundary,width,.64,.24)`：生成互补图像遮罩与文案淡出淡入时序。

先按原图和旁白确定target与rect，再调用坐标助手。将页面全部标题、正文、数字、标签放入copy层；图像与框选放入visual层。完整参数见[画面规范](visual-system.md)。

## 合成音频与字幕

完成独立人声、音乐和混音，以统一对齐时间轴在页面渲染字幕，并由同一时间源导出SRT。

```bash
ffmpeg -i <visual.mp4> -i <mix.wav> -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -ar 48000 -t <actual-duration> -movflags +faststart <final-v1.mp4>
```

混音覆盖完整片长，片尾音乐留出自然收束时间。明确设置最终时长，并核对音画结束位置。

## 验证

```bash
python <skill>/scripts/easel_video.py verify <final-v1.mp4> --duration <actual-duration> --fps 30 --width 1920 --height 1080 --report <project>/qa/final-v1.json --references <project>/qa/references.json
```

references.json示例：`[{"frame":90,"path":"opening-v1.png"}]`。frame为被检查视频内的帧号，path相对该JSON；参考图在相同分辨率、相同帧时间生成。

验证器检查全部帧的解码和PTS，参考图比较默认平均像素误差≤4/255。查看 `technical_pass` 与各项测量结果；按时间点目检 `visual_review_required` 标记。对有意制作的无声工程样片使用 `--allow-silent`。

将检查结果、最终文件哈希和重建参数保存到项目QA。交付当前工程代码、素材、独立音轨及工具，使用包内相对路径。脱离 Easel 使用交付工程时可直接运行工程中的原始 `render.cjs`、`verify_video.py` 和 `paper_assets.py`；自行安装其运行依赖。
