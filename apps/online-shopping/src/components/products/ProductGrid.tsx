import { Suspense } from 'react';
import { getProducts } from '@/lib/api';
import ProductCard from './ProductCard';
import LoadingSpinner from '../ui/LoadingSpinner';

export default async function ProductGrid() {
  const products = await getProducts();

  return (
    <div className="mt-8">
      <h2 className="text-2xl font-bold mb-6">Featured Products</h2>
      <Suspense fallback={<LoadingSpinner />}>
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6">
          {products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      </Suspense>
    </div>
  );
}
