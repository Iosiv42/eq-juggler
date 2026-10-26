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
  float a0_recip, a1, a2, b0, b1, b2, sm1, sm2, w, x_tmp;
  for (uint i = 0; i < filters_count; ++i) {
    a0_recip  = 1.0f / all_a[k_3];
    a1 = all_a[k_3 + 1] * a0_recip;
    a2 = all_a[k_3 + 2] * a0_recip;

    b0 = all_b[k_3] * a0_recip;
    b1 = all_b[k_3 + 1] * a0_recip;
    b2 = all_b[k_3 + 2] * a0_recip;

    sm1 = all_zi[k_2];    // s[-1]
    sm2 = all_zi[k_2 + 1];    // s[-2]

    for (int j = 0; j < x_len; ++j) {
      // Transposed direct form 2

      x_tmp = x[j];
      x[j] = b0*x_tmp+ sm1;
      sm1 = sm2 + b1*x_tmp - a1*x[j];
      sm2 = b2*x_tmp - a2*x[j];
    }

    all_zi[k_2] = sm1;
    all_zi[k_2 + 1] = sm2;

    k_3 += 3;
    k_2 += 2;
  }
}

__attribute__((visibility("default")))
void apply_inplace_double(
  const double* __restrict all_b,
  const double* __restrict all_a,
  float* __restrict x,
  double* __restrict all_zi,
  uint filters_count,
  uint x_len
) {
  uint k_3 = 0, k_2 = 0;
  double a0_recip, a1, a2, b0, b1, b2, sm1, sm2, w, x_tmp, x_new_tmp;
  for (uint i = 0; i < filters_count; ++i) {
    a0_recip  = 1.0 / all_a[k_3];
    a1 = all_a[k_3 + 1] * a0_recip;
    a2 = all_a[k_3 + 2] * a0_recip;

    b0 = all_b[k_3] * a0_recip;
    b1 = all_b[k_3 + 1] * a0_recip;
    b2 = all_b[k_3 + 2] * a0_recip;

    sm1 = all_zi[k_2];    // s[-1]
    sm2 = all_zi[k_2 + 1];    // s[-2]

    for (int j = 0; j < x_len; ++j) {
      // Transposed direct form 2

      x_tmp = x[j];
      x_new_tmp = b0*x_tmp + sm1;
      x[j] = x_new_tmp;
      sm1 = sm2 + b1*x_tmp - a1*x_new_tmp;
      sm2 = b2*x_tmp - a2*x_new_tmp;
    }

    all_zi[k_2] = sm1;
    all_zi[k_2 + 1] = sm2;

    k_3 += 3;
    k_2 += 2;
  }
}
