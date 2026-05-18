import { PaymentGatewayService, PaymentDetails } from '../PaymentGatewayService'
import { Logger } from '@/lib/logger'

// Mock logger
const mockLogger = {
  info: jest.fn(),
  error: jest.fn(),
  warn: jest.fn(),
  debug: jest.fn(),
} as jest.Mocked<Logger>

describe('PaymentGatewayService', () => {
  let paymentService: PaymentGatewayService

  beforeEach(() => {
    jest.clearAllMocks()
    paymentService = new PaymentGatewayService(mockLogger)
  })

  describe('validatePaymentMethod', () => {
    it('should validate credit card payment method', async () => {
      const result = await paymentService.validatePaymentMethod('credit_card')
      expect(result).toBe(true)
      expect(mockLogger.info).toHaveBeenCalled()
    })

    it('should validate debit card payment method', async () => {
      const result = await paymentService.validatePaymentMethod('debit_card')
      expect(result).toBe(true)
      expect(mockLogger.info).toHaveBeenCalled()
    })

    it('should validate bank transfer payment method', async () => {
      const result = await paymentService.validatePaymentMethod('bank_transfer')
      expect(result).toBe(true)
      expect(mockLogger.info).toHaveBeenCalled()
    })
  })

  describe('processPayment', () => {
    const mockPaymentDetails: PaymentDetails = {
      amount: 100,
      currency: 'USD',
      method: 'credit_card',
      description: 'Test payment'
    }

    it('should process payment successfully', async () => {
      const result = await paymentService.processPayment(mockPaymentDetails)
      
      expect(result.success).toBe(true)
      expect(result.transactionId).toBeDefined()
      expect(mockLogger.info).toHaveBeenCalledWith('Processing payment:', mockPaymentDetails)
      expect(mockLogger.info).toHaveBeenCalledWith('Payment processed successfully')
    })

    it('should handle payment processing failure', async () => {
      // Mock Math.random to force failure
      const mockMath = Object.create(global.Math)
      mockMath.random = () => 0.95
      global.Math = mockMath

      const result = await paymentService.processPayment(mockPaymentDetails)
      
      expect(result.success).toBe(false)
      expect(result.error).toBe('Payment processing failed')
      expect(mockLogger.error).toHaveBeenCalled()
    })

    it('should validate payment method before processing', async () => {
      const invalidPaymentDetails: PaymentDetails = {
        ...mockPaymentDetails,
        method: 'invalid_method' as any
      }

      const result = await paymentService.processPayment(invalidPaymentDetails)
      
      expect(result.success).toBe(false)
      expect(result.error).toBe('Invalid payment method')
    })
  })
})
