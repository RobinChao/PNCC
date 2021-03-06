import numpy as np
import scipy
from librosa.core import stft
from librosa import filters


def medium_time_power_calculation(power_stft_signal, M=2):
    medium_time_power = np.zeros_like(power_stft_signal) 
    power_stft_signal = np.pad(power_stft_signal, [(M, M), (0, 0)], 'constant')
    for i in range(medium_time_power.shape[0]):
        medium_time_power[i, :] = sum([1 / (2 * M + 1) * 
                                                       power_stft_signal[i + k - M, :] 
                                                       for k in range(2 * M + 1)])
    return medium_time_power


def asymmetric_lawpass_filtering(rectified_signal, lm_a=0.999, lm_b=0.5):
    floor_level = np.zeros_like(rectified_signal)
    lm_array = np.zeros_like(rectified_signal)
    floor_level[0,] = 0.9 * rectified_signal[0,]
    for m in range(floor_level.shape[0]):
        floor_level[m, ] = np.where(rectified_signal[m,] >= floor_level[m-1,],
                                   lm_a * floor_level[m-1,] + 
                                    (1 - lm_a) * rectified_signal[m,],
                                   lm_b * floor_level[m-1,] + 
                                    (1 - lm_b) * rectified_signal[m,])
        
    return floor_level


def halfwave_rectification(subtracted_lower_envelope, th=0):
    return np.where(subtracted_lower_envelope < th, 
                   np.zeros_like(subtracted_lower_envelope),
                   subtracted_lower_envelope)


def temporal_masking(rectified_signal, lam_t=0.85, myu_t=0.2):
    temporal_masked_signal = np.zeros_like(rectified_signal)
    online_peak_power = np.zeros_like(rectified_signal) 
    temporal_masked_signal[0,] = rectified_signal[0,]
    for m in range(rectified_signal.shape[0]):
        online_peak_power[m, :] = np.where(
            lam_t * online_peak_power[m - 1, :] >= rectified_signal[m, ], 
                                         lam_t * online_peak_power[m - 1, :],
                                         rectified_signal[m, :])
        temporal_masked_signal[m, :] = np.where(
            rectified_signal[m, :] >= lam_t * online_peak_power[m-1, :],
            rectified_signal[m, :],
            myu_t * online_peak_power[m-1, :])

    return temporal_masked_signal


def after_temporal_masking(temporal_masked_signal, floor_level):
    return np.where(temporal_masked_signal > floor_level, 
                   temporal_masked_signal, floor_level)


def switch_excitation_or_non_excitation(temporal_masked_signal,
                                        floor_level, lower_envelope,
                                        medium_time_power, c=2):
    return np.where(medium_time_power >= c * lower_envelope, 
                   temporal_masked_signal, floor_level)

def weight_smoothing(final_output, medium_time_power, N=4, L=40):
    spectral_weight_smoothing = np.zeros_like(final_output) 
    for l in range(final_output.shape[1]):
        l_1 = max(l - N, 1)
        l_2 = min(l + N, L)
        spectral_weight_smoothing[:, l] = sum(
            [1/(l_2 - l_1 + 1) * (final_output[:, k] / np.where(
                medium_time_power[:, k] > 0.0001,
                                                               medium_time_power[:, k], 
                                                               0.0001)) for k in range(l_1, l_2)])
    return spectral_weight_smoothing

def time_frequency_normalization(power_stft_signal,
                                 spectral_weight_smoothing):
    return power_stft_signal * spectral_weight_smoothing


def mean_power_normalization(transfer_function,
                             final_output, lam_myu=0.999, L=40, k=1):
    myu = np.zeros(shape=(transfer_function.shape[0]))
    myu[0] = 0.0001
    normalized_power = np.zeros_like(transfer_function) 
    for m in range(1, transfer_function.shape[0]):
        myu[m] = lam_myu * myu[m - 1] + \
            (1 - lam_myu) / L * \
            sum([transfer_function[m, k] for k in range(0, L-1)])
    for m in range(final_output.shape[0]):
        normalized_power[m, :] = k * transfer_function[m, :] / myu[m]
        
    return normalized_power

def power_function_nonlinearity(normalized_power, n=15):
    return normalized_power ** (1/n)


def pncc(audio_wave, n_fft=1024, sr=16000, window="hamming",
         n_mels=40, n_pncc=13, weight_N=4, power=2, dct=True):

    pre_emphasis_signal = scipy.signal.lfilter([1.0, -0.97], 1, audio_wave)
    stft_pre_emphasis_signal = np.abs(stft(pre_emphasis_signal,
                                      n_fft=n_fft, window=window)) ** power
    mel_filter = np.abs(filters.mel(sr, n_fft=n_fft, n_mels=n_mels)) ** power
    power_stft_signal = np.dot(stft_pre_emphasis_signal.T, mel_filter.T)
    medium_time_power = medium_time_power_calculation(power_stft_signal)
    lower_envelope = asymmetric_lawpass_filtering(
        medium_time_power, 0.999, 0.5)
    
    subtracted_lower_envelope = medium_time_power - lower_envelope
    rectified_signal = halfwave_rectification(subtracted_lower_envelope)
    
    floor_level = asymmetric_lawpass_filtering(rectified_signal)
    
    temporal_masked_signal = temporal_masking(rectified_signal)
    temporal_masked_signal = after_temporal_masking(
        temporal_masked_signal, floor_level)
    
    
    final_output = switch_excitation_or_non_excitation(
        temporal_masked_signal, floor_level, lower_envelope,
        medium_time_power)
    
    spectral_weight_smoothing = weight_smoothing(
        final_output, medium_time_power, weight_N)
    
    transfer_function = time_frequency_normalization(
        power_stft_signal=power_stft_signal,
        spectral_weight_smoothing=spectral_weight_smoothing)
    
    
    normalized_power = mean_power_normalization(
        transfer_function, final_output)
    
    
    power_law_nonlinearity = power_function_nonlinearity(normalized_power)
    
    dct_v = np.dot(filters.dct(
        n_pncc, power_law_nonlinearity.shape[1]), power_law_nonlinearity.T)
    
    return power_law_nonlinearity