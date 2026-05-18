export type CartItem = {
  id: string;
  productId: string;
  quantity: number;
  price: number;
  name: string;
};

export type Cart = {
  id: string;
  userId?: string;
  sessionId: string;
  items: CartItem[];
  createdAt: Date;
  updatedAt: Date;
  total: number;
};

export type CreateCartInput = {
  userId?: string;
  sessionId: string;
};

export type AddCartItemInput = {
  cartId: string;
  productId: string;
  quantity: number;
  price: number;
  name: string;
};

export type UpdateCartItemInput = {
  cartId: string;
  itemId: string;
  quantity: number;
};