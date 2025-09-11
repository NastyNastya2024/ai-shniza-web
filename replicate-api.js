// @ts-nocheck

// Replicate API интеграция для GPT-4o-mini
class ReplicateAPI {
  constructor() {
    this.apiToken = CONFIG.REPLICATE_API_TOKEN;
    this.baseURL = CONFIG.API_BASE_URL;
    this.model = 'openai/gpt-4o-mini';
    this.version = CONFIG.MODEL_VERSION;
  }

  // Отправка запроса к GPT-4o-mini
  async sendMessage(prompt, systemPrompt = "You are a helpful AI assistant for an AI marketplace. Help users with questions about AI models, image generation, and creative tasks. Respond in Russian.") {
    try {
      const response = await fetch(`${this.baseURL}/predictions`, {
        method: 'POST',
        headers: {
          'Authorization': `Token ${this.apiToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          version: this.version,
          input: {
            prompt: prompt,
            system_prompt: systemPrompt,
            temperature: CONFIG.DEFAULT_SETTINGS.temperature,
            max_completion_tokens: CONFIG.DEFAULT_SETTINGS.max_completion_tokens,
            top_p: CONFIG.DEFAULT_SETTINGS.top_p,
            presence_penalty: CONFIG.DEFAULT_SETTINGS.presence_penalty,
            frequency_penalty: CONFIG.DEFAULT_SETTINGS.frequency_penalty,
            messages: [],
            image_input: []
          }
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const prediction = await response.json();
      
      // Ждем завершения обработки
      return await this.waitForCompletion(prediction.id);
      
    } catch (error) {
      console.error('Ошибка при отправке запроса к GPT-4o-mini:', error);
      throw error;
    }
  }

  // Ожидание завершения обработки
  async waitForCompletion(predictionId) {
    const maxAttempts = 30; // Максимум 30 попыток (30 секунд)
    let attempts = 0;

    while (attempts < maxAttempts) {
      try {
        const response = await fetch(`${this.baseURL}/predictions/${predictionId}`, {
          headers: {
            'Authorization': `Token ${this.apiToken}`,
          }
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const prediction = await response.json();

        if (prediction.status === 'succeeded') {
          return prediction.output;
        } else if (prediction.status === 'failed') {
          throw new Error(`Prediction failed: ${prediction.error}`);
        }

        // Ждем 1 секунду перед следующей проверкой
        await new Promise(resolve => setTimeout(resolve, 1000));
        attempts++;

      } catch (error) {
        console.error('Ошибка при проверке статуса:', error);
        throw error;
      }
    }

    throw new Error('Timeout: Prediction took too long to complete');
  }

  // Отправка сообщения с изображением (если загружено)
  async sendMessageWithImage(prompt, imageData, systemPrompt = "You are a helpful AI assistant for an AI marketplace. Help users with questions about AI models, image generation, and creative tasks. You can also analyze uploaded images. Respond in Russian.") {
    try {
      const response = await fetch(`${this.baseURL}/predictions`, {
        method: 'POST',
        headers: {
          'Authorization': `Token ${this.apiToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          version: this.version,
          input: {
            prompt: prompt,
            system_prompt: systemPrompt,
            temperature: CONFIG.DEFAULT_SETTINGS.temperature,
            max_completion_tokens: CONFIG.DEFAULT_SETTINGS.max_completion_tokens,
            top_p: CONFIG.DEFAULT_SETTINGS.top_p,
            presence_penalty: CONFIG.DEFAULT_SETTINGS.presence_penalty,
            frequency_penalty: CONFIG.DEFAULT_SETTINGS.frequency_penalty,
            messages: [],
            image_input: imageData ? [imageData] : []
          }
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const prediction = await response.json();
      return await this.waitForCompletion(prediction.id);
      
    } catch (error) {
      console.error('Ошибка при отправке запроса с изображением:', error);
      throw error;
    }
  }
}

// Экспорт для использования в других файлах
window.ReplicateAPI = ReplicateAPI;
