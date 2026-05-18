export interface CartItem {
  id: string;
  name: string;
  price: number;
  quantity: number;
  imageUrl?: string;
}

export interface CartSummary {
  totalItems: number;
  subtotal: number;
  items: CartItem[];
}

export type CartEventType = 'itemAdded' | 'itemRemoved' | 'cartCleared' | 'quantityChanged';

export interface CartEvent {
  type: CartEventType;
  item?: CartItem;
}