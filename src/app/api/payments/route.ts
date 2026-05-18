import { NextResponse } from 'next/server'
import { PaymentGatewayService, PaymentDetails } from '@/lib/payment/PaymentGatewayService'
import { Logger } from '@/lib/logger'

const logger = new Logger() // Initialize your logger
const paymentService = new PaymentGatewayService(logger)

export async function POST(request: Request) {
  try {
    const body = await request.json()
    
    // Validate request body
    if (!isValidPaymentRequest(body)) {
      return NextResponse.json(
        { error: 'Invalid payment details' },
        { status: 400 }
      )
    }

    const paymentDetails: PaymentDetails = {
      amount: body.amount,
      currency: body.currency,
      method: body.method,
      description: body.description,
      metadata: body.metadata
    }

    const result = await paymentService.processPayment(paymentDetails)

    if (!result.success) {
      return NextResponse.json(
        { error: result.error },
        { status: 400 }
      )
    }

    return NextResponse.json({
      success: true,
      transactionId: result.transactionId
    })
  } catch (error) {
    logger.error('Payment processing error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

function isValidPaymentRequest(body: any): body is PaymentDetails {
  return (
    typeof body === 'object' &&
    typeof body.amount === 'number' &&
    typeof body.currency === 'string' &&
    ['credit_card', 'debit_card', 'bank_transfer'].includes(body.method) &&
    (body.description === undefined || typeof body.description === 'string') &&
    (body.metadata === undefined || typeof body.metadata === 'object')
  )
}
