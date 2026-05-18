import { Product } from '@/types/product';

export async function getProducts(): Promise<Product[]> {
  try {
    const response = await fetch('/api/products');
    if (!response.ok) throw new Error('Failed to fetch products');
    return response.json();
  } catch (error) {
    console.error('Error fetching products:', error);
    throw error;
  }
}

export async function getProduct(id: string): Promise<Product> {
  try {
    const response = await fetch(`/api/products/${id}`);
    if (!response.ok) throw new Error('Failed to fetch product');
    return response.json();
  } catch (error) {
    console.error('Error fetching product:', error);
    throw error;
  }
}
