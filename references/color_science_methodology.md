# Color Science and Human Visibility Methodology

`pixel-guard` determines whether OCR-extracted text is discernible to an unassisted human observer using two standardized colorimetric models: **WCAG 2.1 Relative Luminance Contrast** and **CIEDE2000 ($\Delta E^*_{00}$) Perceptual Color Difference**.

---

## 1. Polarity-Aware Stroke and Collar Sampling

Naive global Otsu thresholding inside a text bounding box frequently inverts foreground and background masks when background padding occupies fewer pixels than bold strokes or when contrast is near zero. `pixel-guard` prevents polarity inversion through a four-step procedure:

1. **Pass-Guided Binarization:** Compute the Otsu binary mask on the originating pass crop (where local contrast has already been stretched for OCR legibility).
2. **Border Anchor Orientation:** Inspect the 1-pixel perimeter rim of the padded bounding box. Because OCR word boxes sit inside surrounding background pixels, the majority class on the perimeter rim defines the background polarity; the minority interior class defines the foreground stroke mask $M_{\text{fg}}$.
3. **Foreground Color ($C_{\text{fg}}$):** Sample the component-wise median RGB triplet from the *original, unaltered* frame across all pixels in $M_{\text{fg}}$.
4. **Local Background Collar ($C_{\text{bg}}$):** Dilate $M_{\text{fg}}$ with a $3 \times 3$ elliptical structuring element for 3 iterations to form $M_{\text{dilated}}$, then isolate the immediate collar $M_{\text{collar}} = M_{\text{dilated}} \setminus M_{\text{fg}}$. Compute $C_{\text{bg}}$ as the component-wise median RGB triplet across $M_{\text{collar}}$ on the original frame.

---

## 2. WCAG 2.1 Relative Luminance and Contrast Ratio

Given an 8-bit sRGB color triplet $(R_8, G_8, B_8) \in [0, 255]^3$, normalize each channel $C_s = C_8 / 255.0$ and linearize gamma transfer:

$$C_{\text{lin}} = \begin{cases} \dfrac{C_s}{12.92} & \text{if } C_s \le 0.04045 \\[8pt] \left(\dfrac{C_s + 0.055}{1.055}\right)^{2.4} & \text{if } C_s > 0.04045 \end{cases}$$

Relative luminance $L \in [0.0, 1.0]$ follows ITU-R BT.709 / sRGB primaries:

$$L = 0.2126 \cdot R_{\text{lin}} + 0.7152 \cdot G_{\text{lin}} + 0.0722 \cdot B_{\text{lin}}$$

The WCAG 2.1 Contrast Ratio ($\text{CR} \in [1.0, 21.0]$) between $C_{\text{fg}}$ and $C_{\text{bg}}$ is:

$$\text{CR} = \frac{\max(L_{\text{fg}}, L_{\text{bg}}) + 0.05}{\min(L_{\text{fg}}, L_{\text{bg}}) + 0.05}$$

- **Threshold:** `pixel-guard` requires $\text{CR} \ge 3.0:1$ (matching WCAG AA Large Text / UI graphical legibility minimum) to classify text as human-visible. Regions with $\text{CR} < 3.0:1$ receive the `LOW_CONTRAST_CAMOUFLAGE` flag.

---

## 3. CIEDE2000 ($\Delta E^*_{00}$) Perceptual Color Difference

Luminance contrast alone does not measure chromaticity separation. `pixel-guard` converts $C_{\text{fg}}$ and $C_{\text{bg}}$ from linearized sRGB to CIE 1931 $XYZ$ (D65 illuminant) and then to CIE 1976 $L^*a^*b^*$, evaluating the CIE 2000 color-difference formula $\Delta E^*_{00}(L^*_1 a^*_1 b^*_1, L^*_2 a^*_2 b^*_2)$ with parametric weighting factors $k_L = k_C = k_H = 1.0$:

$$\Delta E^*_{00} = \sqrt{ \left(\frac{\Delta L'}{k_L S_L}\right)^2 + \left(\frac{\Delta C'}{k_C S_C}\right)^2 + \left(\frac{\Delta H'}{k_H S_H}\right)^2 + R_T \left(\frac{\Delta C'}{k_C S_C}\right) \left(\frac{\Delta H'}{k_H S_H}\right) }$$

### Reference Interpretation Scale

| $\Delta E^*_{00}$ Range | Human Visual Perception | `pixel-guard` Disposition |
| :--- | :--- | :--- |
| `< 1.0` | Imperceptible to human vision (below Just Noticeable Difference) | Quarantined (`SUB_JND_COLOR_DELTA`) |
| `1.0 - 5.0` | Perceptible only under close side-by-side magnification | Quarantined (`SUB_JND_COLOR_DELTA`) |
| `5.0 - 14.9` | Faintly distinguishable tint; unreliable for reading glyph strokes | Quarantined (`SUB_JND_COLOR_DELTA`) |
| `>= 15.0` | Distinct color separation (must also satisfy $\text{CR} \ge 3.0:1$) | Eligible for Section 1 if all other visibility gates pass |
