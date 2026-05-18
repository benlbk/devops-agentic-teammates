import ProductGrid from '@/components/products/ProductGrid';
import FeaturedCategories from '@/components/home/FeaturedCategories';
import HeroBanner from '@/components/home/HeroBanner';

export default async function HomePage() {
  return (
    <div className="container mx-auto px-4">
      <HeroBanner />
      <FeaturedCategories />
      <ProductGrid />
    </div>
  );
}
