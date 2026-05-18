export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
}

export interface RegisterResponse {
  message: string;
  user: {
    id: string;
    email: string;
    name: string;
    createdAt: Date;
  };
}

export interface ErrorResponse {
  error: string;
  details?: Array<{
    code: string;
    message: string;
    path: string[];
  }>;
}
