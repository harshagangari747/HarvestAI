import axios from 'axios'

const API_ENDPOINT = import.meta.env.VITE_API_ENDPOINT || 'http://localhost:3001'

const client = axios.create({
  baseURL: API_ENDPOINT,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor
client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('authToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('authToken')
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

export const fieldAPI = {
  // List all active fields
  listFields: () =>
    client.get('/fields'),

  // Create a new field
  createField: (fieldData) =>
    client.post('/fields', fieldData),

  // Get field metadata
  getField: (fieldId) =>
    client.get(`/fields/${fieldId}`),

  // Get latest daily status
  getLatestStatus: (fieldId) =>
    client.get(`/fields/${fieldId}/status/latest`),

  // Get field time series data
  getTimeSeries: (fieldId) =>
    client.get(`/fields/${fieldId}/timeseries`),

  // Get field map data
  getMapData: (fieldId) =>
    client.get(`/fields/${fieldId}/maps/latest`),

  // Get satellite observations (gallery)
  getObservations: (fieldId) =>
    client.get(`/fields/${fieldId}/observations`),

  // Delete a field (soft-delete)
  deleteField: (fieldId) =>
    client.delete(`/fields/${fieldId}`),

  // Trigger batch run manually
  triggerBatch: (fieldId) =>
    client.post(`/fields/${fieldId}/run`)
}

export default client
