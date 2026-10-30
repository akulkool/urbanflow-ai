import apiClient from './apiClient';
import { MOCK_VISION_ANALYSIS } from '../utils/mockTrafficData';

/**
 * Computer Vision & AI Traffic Monitoring Service.
 * Handles video file validation, multipart upload, progress tracking,
 * and analysis result parsing.
 */
const visionService = {
  /**
   * Validate uploaded video file.
   * Checks file extension and maximum file size (100MB).
   */
  validateFile: (file) => {
    if (!file) {
      return { valid: false, error: 'No file selected.' };
    }

    const allowedTypes = [
      'video/mp4',
      'video/quicktime', // .mov
      'video/x-msvideo', // .avi
      'video/webm',
    ];

    const extension = file.name.split('.').pop().toLowerCase();
    const allowedExtensions = ['mp4', 'mov', 'avi', 'webm'];

    if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(extension)) {
      return {
        valid: false,
        error: `Unsupported file format (.${extension}). Please upload an MP4, AVI, MOV, or WEBM video file.`,
      };
    }

    const maxSizeBytes = 100 * 1024 * 1024; // 100MB
    if (file.size > maxSizeBytes) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
      return {
        valid: false,
        error: `File size (${sizeMB} MB) exceeds maximum limit of 100 MB.`,
      };
    }

    return { valid: true, error: null };
  },

  /**
   * Analyze uploaded traffic video via backend Vision API.
   * Endpoint: POST /traffic/analyze
   *
   * @param {File} file - Video file from file input or drag-and-drop
   * @param {Function} onProgress - Callback for upload percentage (0 - 100)
   */
  analyzeVideo: async (file, onProgress) => {
    const formData = new FormData();
    formData.append('video', file);

    try {
      const response = await apiClient.post('/traffic/analyze', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total && onProgress) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            onProgress(percent);
          }
        },
      });

      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      // Document the missing backend Vision API requirement
      return {
        data: null,
        isLive: false,
        error: err.response?.data?.detail || err.message || 'Vision API service unavailable',
        missingEndpoint: 'POST /api/traffic/analyze (Multipart FormData: video)',
        statusCode: err.response?.status || 'OFFLINE',
      };
    }
  },

  /**
   * Return verified demonstration telemetry for interface testing
   * when backend computer vision model is not deployed.
   */
  getDemoTelemetry: () => {
    return {
      data: MOCK_VISION_ANALYSIS,
      isLive: false,
      isDemo: true,
      label: 'Bengaluru Simulated Vision Telemetry',
    };
  },
};

export default visionService;

