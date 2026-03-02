#!/usr/bin/env python3
"""apply_weather_video.py — 为晴天视频添加高质量雨夜特效（后处理）。

功能：
  1. 读取 MP4 视频逐帧处理
  2. 应用 RainNightFilter：
     - Color Grading：压暗背景，增加冷色调（夜晚氛围）
     - Bloom：提取高光区域并模糊叠加（灯光散射）
     - Wet Reflection：垂直翻转并模糊，叠加在地面区域（积水倒影）
     - Multi-Layer Rain：多层雨滴叠加（近景虚、中景实、远景雾），带风向倾斜
  3. 导出新 MP4 视频

用法：
  python scripts/apply_weather_video.py \\
    --input data/output/scene-0061_sunny_v3.mp4 \\
    --output data/output/scene-0061_rainy_night_v5.mp4 \\
    --bloom-intensity 2.0 \\
    --rain-intensity 0.9
"""
import argparse
import cv2
import numpy as np
import random


class RainLayer:
    """单个雨滴层，拥有独立的密度、大小、速度和模糊度。"""
    def __init__(self, width, height, scale=1.0, speed=10, blur_angle=15, blur_len=10, density=0.01):
        self.w = width
        self.h = height
        self.speed = speed
        # 内部渲染分辨率（通过 scale 缩放来实现不同大小的雨滴）
        self.rw = int(width * scale)
        self.rh = int(height * scale)
        
        # 预生成噪声图
        # 使用稀疏噪声：大部分是0
        # density 控制非零点的比例
        num_drops = int(self.rw * self.rh * density)
        self.noise = np.zeros((self.rh, self.rw), dtype=np.float32)
        
        # 随机撒点
        x = np.random.randint(0, self.rw, num_drops)
        y = np.random.randint(0, self.rh, num_drops)
        # 雨滴亮度随机 (0.5 ~ 1.0)
        v = np.random.uniform(0.5, 1.0, num_drops)
        self.noise[y, x] = v

        # 生成运动模糊核 (Motion Blur Kernel)
        # 模拟风向倾斜
        kernel_size = max(blur_len, 3)
        kernel = np.zeros((kernel_size, kernel_size))
        # 绘制一条线
        center = kernel_size // 2
        # tan(angle) = x / y
        tan_a = np.tan(np.radians(blur_angle))
        for i in range(kernel_size):
            offset_y = i - center
            offset_x = int(offset_y * tan_a)
            cx = center + offset_x
            if 0 <= cx < kernel_size:
                kernel[i, cx] = 1.0
        kernel /= kernel.sum() # 归一化
        self.kernel = kernel
        
        # 对噪声图预先做模糊，生成"雨帘"纹理
        self.rain_texture = cv2.filter2D(self.noise, -1, self.kernel)
        
        # 当前滚动偏移量
        self.offset_y = 0.0
        self.offset_x = 0.0

    def get_frame(self):
        """获取当前帧的雨滴遮罩（与原图同尺寸）。"""
        # 计算滚动
        dy = self.speed
        dx = self.speed * np.tan(np.radians(15)) # 假设风向 15 度
        
        self.offset_y = (self.offset_y + dy) % self.rh
        self.offset_x = (self.offset_x + dx) % self.rw
        
        oy = int(self.offset_y)
        ox = int(self.offset_x)
        
        # 滚动纹理
        rolled = np.roll(self.rain_texture, oy, axis=0)
        rolled = np.roll(rolled, ox, axis=1)
        
        # 缩放回原图尺寸
        # INTER_LINEAR 会让雨滴更柔和
        rain_mask = cv2.resize(rolled, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        return rain_mask


class RainNightFilter:
    def __init__(self, width, height, rain_intensity=0.8, bloom_intensity=1.5):
        self.w = width
        self.h = height
        self.rain_intensity = rain_intensity
        self.bloom_intensity = bloom_intensity
        
        # 初始化多层雨滴
        # Layer 1: 远景（雾状，密，慢，小）
        self.layer_far = RainLayer(width, height, scale=0.5, speed=15, blur_len=5, density=0.05 * rain_intensity)
        # Layer 2: 中景（清晰，中等速度）
        self.layer_mid = RainLayer(width, height, scale=0.2, speed=30, blur_len=15, density=0.005 * rain_intensity)
        # Layer 3: 近景（急速，大，虚，稀疏）
        self.layer_near = RainLayer(width, height, scale=0.1, speed=60, blur_len=40, density=0.001 * rain_intensity)

    def process(self, img_bgr):
        """处理单帧图像 (BGR uint8) -> (BGR uint8)。"""
        # 1. 转为 float32
        img_f = img_bgr.astype(np.float32) / 255.0

        # 2. Color Grading (色调映射) - 保持 v4 的冷色调
        img_f = np.power(img_f, 2.0)  # Gamma 略微提亮一点暗部细节，v4 的 2.2 有点太黑了
        img_f[:, :, 0] *= 1.25 # Blue
        img_f[:, :, 1] *= 1.05 # Green
        img_f[:, :, 2] *= 0.85 # Red
        
        # 3. Bloom (辉光)
        bright_mask = np.maximum(img_f - 0.6, 0) # 阈值降低一点，让更多光晕出来
        bloom = cv2.GaussianBlur(bright_mask, (0, 0), sigmaX=25, sigmaY=25) # 模糊半径加大
        img_f += bloom * self.bloom_intensity

        # 4. Wet Road Reflection (湿地反射)
        horizon_y = int(self.h * 0.55) # 地平线稍微提一点
        reflection_roi = img_f[horizon_y:, :]
        source_h = self.h - horizon_y
        source_roi = img_f[horizon_y - source_h : horizon_y, :]
        reflection = cv2.flip(source_roi, 0)
        reflection = cv2.GaussianBlur(reflection, (0, 0), sigmaX=30, sigmaY=5) # 横向模糊更强（动感）
        mask = np.linspace(0.1, 0.5, source_h).reshape(-1, 1, 1) # 反射弱一点，不要太抢眼
        img_f[horizon_y:, :] = img_f[horizon_y:, :] * 0.7 + reflection * mask

        # 5. Multi-Layer Rain (多层雨滴叠加)
        rain_far = self.layer_far.get_frame()
        rain_mid = self.layer_mid.get_frame()
        rain_near = self.layer_near.get_frame()
        
        # 叠加雨滴
        # 远景：像雾气，加白
        img_f += rain_far[:, :, None] * 0.15
        
        # 中景：清晰雨丝，混合叠加（Screen mode simul）
        # img = 1 - (1-img)*(1-rain)
        rain_mid_3c = rain_mid[:, :, None]
        img_f = 1.0 - (1.0 - img_f) * (1.0 - rain_mid_3c * 0.4)
        
        # 近景：急速划过的虚影，透明度低但影响大
        img_f += rain_near[:, :, None] * 0.2

        # 6. 最终修正
        img_f = np.clip(img_f, 0, 1)
        img_out = (img_f * 255).astype(np.uint8)
        
        return img_out


def main():
    parser = argparse.ArgumentParser(description="生成高质量雨夜特效视频")
    parser.add_argument("--input", required=True, help="输入晴天视频路径")
    parser.add_argument("--output", required=True, help="输出雨夜视频路径")
    parser.add_argument("--bloom-intensity", type=float, default=1.8, help="辉光强度")
    parser.add_argument("--rain-intensity", type=float, default=1.0, help="雨量强度")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        print(f"Error: 无法打开输入视频 {args.input}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[雨夜滤镜 v5] 输入: {width}x{height} @ {fps}fps, {total_frames} 帧")
    
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.output, fourcc, fps, (width, height))
    
    processor = RainNightFilter(width, height, args.rain_intensity, args.bloom_intensity)

    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        processed_frame = processor.process(frame)
        writer.write(processed_frame)
        
        count += 1
        if count % 10 == 0:
            print(f"  处理进度: {count}/{total_frames} ({(count/total_frames)*100:.1f}%) ...")

    cap.release()
    writer.release()
    print(f"[雨夜滤镜 v5] 完成！保存至: {args.output}")


if __name__ == "__main__":
    main()
