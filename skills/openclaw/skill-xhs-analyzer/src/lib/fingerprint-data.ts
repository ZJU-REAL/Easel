/**
 * Fingerprint data constants for generating realistic browser fingerprints.
 * Ported from: Cloxl/xhshow data/fingerprint_data.py
 */

export const GPU_VENDORS = [
  "Google Inc. (Intel)|ANGLE (Intel, Intel(R) HD Graphics 520 (0x1912) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (Intel)|ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00003EA0) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (Intel)|ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (Intel)|ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x000046A8) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (AMD)|ANGLE (AMD, AMD Radeon Graphics (0x00001636) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (AMD)|ANGLE (AMD, AMD Radeon RX 580 2048SP (0x00006FDF) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (AMD)|ANGLE (AMD, AMD Radeon RX 6600 XT (0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (NVIDIA)|ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB (0x000010DE) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (NVIDIA)|ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x0000250F) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (NVIDIA)|ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 (0x00002488) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (NVIDIA)|ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 (0x00002882) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (NVIDIA)|ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 (0x00002786) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (NVIDIA)|ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 (0x00002684) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "Google Inc. (Google)|ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)",
];

export const SCREEN_RESOLUTIONS = {
  resolutions: [
    "1366;768",
    "1600;900",
    "1920;1080",
    "2560;1440",
    "3840;2160",
  ],
  weights: [0.25, 0.15, 0.4, 0.15, 0.05],
};

export const FINGERPRINT_DEFAULTS = {
  browserPlugins:
    "PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer,Microsoft Edge PDF Viewer,WebKit built-in PDF",
  fonts:
    'system-ui, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji", -apple-system, "Segoe UI", Roboto, Ubuntu, Cantarell, "Noto Sans", sans-serif, BlinkMacSystemFont, "Helvetica Neue", Arial, "PingFang SC", "PingFang TC", "PingFang HK", "Microsoft Yahei", "Microsoft JhengHei"',
};
