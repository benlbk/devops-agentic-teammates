import { NextResponse } from 'next/server';
import type { Product } from '@/types/product';

export async function GET() {
  try {
    // In a real app, this would fetch from a database
    const products: Product[] = [
      {
        id: '1',
        name: 'Sample Product',
        description: 'This is a sample product',
        price: 99.99,
        imageUrl: '/sample-product.jpg',
        category: 'Electronics',
        stock: 10,
        rating: 4.5,
        reviews: []
      }
    ];

    return NextResponse.json(products);
  } catch (error) {
    return NextResponse.json(
      { error: 'Failed to fetch products' },
      { status: 500 }
    );
  }
}
