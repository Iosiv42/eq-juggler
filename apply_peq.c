#include <sys/types.h>
void apply_inplace(float* all_b, float* all_a, float* x, float* all_zi, uint filters_count, uint x_len) {
  for (uint i = 0; i < filters_count; i++) {
    uint k = 3*i;
    float a0  = all_a[k];
    float a1 = all_a[k + 1] / a0;
    float a2 = all_a[k + 2] / a0;

    float b0 = all_b[k] / a0;
    float b1 = all_b[k + 1] / a0;
    float b2 = all_b[k + 2] / a0;

    k = 2*i;
    float wm1 = all_zi[k];    // w[-1]
    float wm2 = all_zi[k + 1];    // w[-2]

    for (int j = 0; j < x_len; j++) {
      float w = x[j] - a1*wm1 - a2*wm2;
      x[j] = b0*w + b1*wm1 + b2*wm2;

      wm2 = wm1;
      wm1 = w;
    }

    all_zi[k] = wm1;
    all_zi[k + 1] = wm2;
  }
}
