#include <stdio.h>
#include <sys/types.h>
#include <complex.h>
#include <stdlib.h>
#include <float.h>

#define _USE_MATH_DEFINES
#include <math.h>

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


__attribute__((visibility("default")))
double max_gain(
  const double* __restrict all_b,
  const double* __restrict all_a,
  uint filters_count,
  uint freq_bins_count,
  double preamp_gain_db
) {
  double 
    a0, a1, a2,
    b0, b1, b2;

  double *mag_sq = malloc(freq_bins_count * sizeof(double));
  double *k1_cache = malloc(freq_bins_count * sizeof(double));
  double *k2_cache = malloc(freq_bins_count * sizeof(double));

  double w = 0, inc = M_PI/(freq_bins_count - 1);
  for (uint i = 0; i < freq_bins_count; i++) {
    mag_sq[i] = 1.0;

    double k = 1 - cos(w);
    k1_cache[i] = k;
    k2_cache[i] = k*k;

    w += inc;
  }

  for (uint i = 0; i < 3*filters_count; i += 3) {
    a0 = all_a[i];
    a1 = all_a[i + 1];
    a2 = all_a[i + 2];

    b0 = all_b[i];
    b1 = all_b[i + 1];
    b2 = all_b[i + 2];

    double
      n_c0 = (b0 + b1 + b2) * (b0 + b1 + b2),
      n_c1 = 2 * (b0*b1 + b1*b2 + 4*b0*b2),
      n_c2 = 4*b0*b2,

      d_c0 = (a0 + a1 + a2) * (a0 + a1 + a2),
      d_c1 = 2 * (a0*a1 + a1*a2 + 4*a0*a2),
      d_c2 = 4*a0*a2;

    for (uint j = 0; j < freq_bins_count; j++) {
      double k1 = k1_cache[j], k2 = k2_cache[j];
      mag_sq[j] *= 
        (n_c0 - n_c1*k1 + n_c2*k2) / (d_c0 - d_c1*k1 + d_c2*k2);
    }
  }

  double max_sq = DBL_MIN, val;
  for (uint i = 0; i < freq_bins_count; i++) {
    val = mag_sq[i];
    if (val > max_sq) {
      max_sq = val;
    }
  }

  free(mag_sq);
  mag_sq = NULL;

  return 10*log10(max_sq) + preamp_gain_db;
}
