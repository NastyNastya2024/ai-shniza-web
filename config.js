// @ts-nocheck

// Конфигурация API
const CONFIG = {
  // Replicate API токен
  // Получите токен на https://replicate.com/account/api-tokens
  REPLICATE_API_TOKEN: 'r8_FUAFZLw6OQ3uQXPHHvNvffVmoogeydf2NNxLT',
  
  // Версия модели GPT-4o-mini
  MODEL_VERSION: '2c0a6a34916017ceafaaf5fdf63f9370cf9491866a9611f37d86138c8ef53fc6',
  
  // Базовый URL API
  API_BASE_URL: 'https://api.replicate.com/v1',
  
  // Настройки по умолчанию
  DEFAULT_SETTINGS: {
    temperature: 0.7,
    max_completion_tokens: 2048,
    top_p: 1,
    presence_penalty: 0,
    frequency_penalty: 0
  }
};

// Экспорт для использования в других файлах
window.CONFIG = CONFIG;
