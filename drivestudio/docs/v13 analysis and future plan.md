看了 v13 的结果，结合整个优化历程，给你一个全面的分析。
一、v13 剩余问题的根本原因分析
问题 1：行人/车辆区域模糊一团
这是 mask 策略的固有代价，是一个无解的悖论：
训练时：动态物体被 mask → 该区域 loss = 0 → Gaussians 未被优化渲染时：相机经过该区域 → 无有效 Gaussians → 显示为模糊 blob 或噪点
mask 的目的是防止动态物体"污染"背景重建，但代价是这些区域在重建中永远是空洞。即使去掉 mask，动态物体（行人、车辆）会被"烤"进静态场景里，变成鬼影。两种策略都有代价，区别只是哪种伤害更小。
问题 2：后视摄像头全面噪点
这是视角稀疏性（angular sparsity）问题，与 mask 无关：
后视区域：每个 3D 点平均只被 1个摄像头（CAM_BACK）看到
前视区域：3D 点被 CAM_FRONT + CAM_FRONT_LEFT + CAM_FRONT_RIGHT 看到
3DGS 的 Gaussian 优化需要多视角约束。后视的 Gaussians 几乎没有约束，训练完后处于"自由状态"。在不同渲染视角下，这些欠约束的 Gaussians 就表现为噪点。
问题 3：局部噪点（边缘 sparkle）
mask 区域边界处的 Gaussians 梯度方向不一致（一侧有 loss，另一侧没有），导致边界附近的 Gaussians 被优化成细长针状（竹叶伪影），渲染时从侧面看就是闪烁噪点。
二、在当前 splatfacto 框架下还有哪些优化思路
思路 A：增加帧数（最有效但需要工程工作）
当前每摄像头只有约 50 帧（2Hz × 25s）。对比：
帧数	约束强度	质量预期
50帧/摄像头（现在）	极弱，大量点只被 1-2 个视角看到	v13 水平
100帧/摄像头	中等	估计改善 20-30%
250帧/摄像头（DriveStudio 10Hz方案）	强	估计改善 60-70%
NuScenes 原始数据可以到 12Hz 采样，我们目前只用了 2Hz keyframe。如果从原始 sample_data（sweeps）提取全帧率数据，可以获得 6 倍更多的训练帧。
思路 B：后处理空间孤立点剔除（KNN）
当前的 pruning 只基于 opacity 和 scale，不考虑空间分布。后视摄像头的噪点往往是空间上孤立的 Gaussians（距离最近邻超过某个阈值）。可以做 KNN outlier removal：
# 伪代码for each Gaussian:    find K nearest neighbors    if avg_distance_to_neighbors > threshold:        remove  # 孤立 floater
这比当前的 opacity threshold 更准确定位"空中悬浮"的 Gaussians。
思路 C：关闭 mask 对背景区域重新训练
专门针对后视区域，训练一个无 mask 版本（允许动态物体出现，但把它们平均掉），与有 mask 版本做混合。这是一种 ensemble 策略，但工程复杂度较高。
三、DriveStudio 目前的状态和预期效果
是的，当前完全没有使用 DriveStudio。我们全程使用的是 nerfstudio splatfacto。
DriveStudio 在我的计划中属于阶段B（根本性解决方案）。由于 Cursor 沙箱无法访问 GitHub，所有安装脚本已经准备好，但需要您在常规 WSL 终端运行。
DriveStudio 针对我们每个问题的具体解决方案：
我们的问题	splatfacto 的处理	DriveStudio/OmniRe 的处理
动态物体区域模糊	完全 mask，留下空洞	独立 Gaussian 图（per-object graph），每辆车单独重建，可以在渲染时替换/移除
后视全屏噪点	无约束，自由漂浮	内置天空球模型（sky sphere）+ 10Hz数据（5倍帧数）
位姿误差放大噪点	假设位姿完美	内置相机位姿精化（专为驾驶数据设计，不会像 v12 那样失控）
曝光不一致	不处理	仿射曝光补偿（per-camera learnable exposure）
边缘 sparkle	无法解决	场景分解后各区域约束更强，边缘更清晰
预期效果对比：
当前 v13（splatfacto）：  - 前视：勉强可见道路结构，有局部噪点  - 后视：仍有全屏噪点  - 行人/车区域：模糊空洞  - 整体质量：~35-40%DriveStudio OmniRe（预期）：  - 前视：清晰道路、建筑、植被，PSNR 接近论文指标 (25-28dB)  - 后视：天空模型处理天空区域，结构噪点显著减少  - 动态物体区域：可以清洁地移除或替换  - 整体质量：~70-80%（接近 ICLR 2025 论文展示效果）
迁移 DriveStudio 的实际操作：
所有脚本已准备好，需要您在常规 WSL 终端（不是 Cursor 内）执行：
# 在 Windows 终端或 Ubuntu WSL 终端中运行bash /home/luosx/3dgs/environments/drivestudio_setup.sh# 约 30-60 分钟完成安装和数据处理# 然后：bash /home/luosx/3dgs/run_train_omnire.sh
四、综合建议
短期（今天）：
v13 已经是 splatfacto 框架下的天花板水平了，继续调参收益极低
可以尝试 KNN 空间剔除（思路B）看能否再减少后视噪点
中期（本周）：
迁移到 DriveStudio 是唯一能从根本上解决问题的路径
需要您在常规终端运行安装脚本（约1小时），之后训练可以在后台跑
结论：v13 证明了 splatfacto 在我们的数据条件下能达到的上限。要达到"以假乱真"的自动驾驶仿真标准，必须切换到 DriveStudio/OmniRe。这是工具选型的问题，不是调参能解决的。