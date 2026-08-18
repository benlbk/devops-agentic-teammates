import { useState } from 'react'

'use client'

interface FeatureState {
  isActive: boolean
  data: string | null
  error: string | null
}

export default function FeatureComponent() {
  const [state, setState] = useState<FeatureState>({
    isActive: false,
    data: null,
    error: null
  })

  const handleAction = async () => {
    try {
      setState(prev => ({ ...prev, isActive: true, error: null }))
      
      // Simulated API call
      const response = await fetch('/api/feature')
      if (!response.ok) throw new Error('Request failed')
      
      const data = await response.json()
      setState(prev => ({ ...prev, data: data.message }))
    } catch (err) {
      setState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'An error occurred'
      }))
    } finally {
      setState(prev => ({ ...prev, isActive: false }))
    }
  }

  return (
    <div className="p-4 border rounded-lg shadow-sm">
      <button
        onClick={handleAction}
        disabled={state.isActive}
        className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
      >
        {state.isActive ? 'Processing...' : 'Perform Action'}
      </button>

      {state.data && (
        <div className="mt-4 p-4 bg-green-50 text-green-700 rounded">
          {state.data}
        </div>
      )}

      {state.error && (
        <div className="mt-4 p-4 bg-red-50 text-red-700 rounded">
          {state.error}
        </div>
      )}
    </div>
  )
}
