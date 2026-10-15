#include <sys/types.h>

__attribute__((visibility("default")))
void apply_inplace(
  const float* __restrict all_b,
  const float* __restrict all_a,
  float* __restrict x,
  float* __restrict all_zi,
  uint filters_count,
  uint x_len
) {
  uint k_3 = 0, k_2 = 0;
  float a0_recip, a1, a2, b0, b1, b2, wm1, wm2, w;
  for (uint i = 0; i < filters_count; ++i) {
    a0_recip  = 1.0f / all_a[k_3];
    a1 = all_a[k_3 + 1] * a0_recip;
    a2 = all_a[k_3 + 2] * a0_recip;

    b0 = all_b[k_3] * a0_recip;
    b1 = all_b[k_3 + 1] * a0_recip;
    b2 = all_b[k_3 + 2] * a0_recip;

    wm1 = all_zi[k_2];    // w[-1]
    wm2 = all_zi[k_2 + 1];    // w[-2]

    for (int j = 0; j < x_len; ++j) {
      w = x[j] - a1*wm1 - a2*wm2;
      x[j] = b0*w + b1*wm1 + b2*wm2;

      wm2 = wm1;
      wm1 = w;
    }

    all_zi[k_2] = wm1;
    all_zi[k_2 + 1] = wm2;

    k_3 += 3;
    k_2 += 2;
  }
}
