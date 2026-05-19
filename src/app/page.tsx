import { Suspense } from 'react'
import FeatureComponent from '@/components/FeatureComponent'
import LoadingSpinner from '@/components/LoadingSpinner'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function Home() {
  return (
    <main className="min-h-screen p-8">
      <h1 className="text-3xl font-bold mb-8">Generic Feature</h1>
      <ErrorBoundary>
        <Suspense fallback={<LoadingSpinner />}>
          <FeatureComponent />
        </Suspense>
      </ErrorBoundary>
    </main>
  )
}
