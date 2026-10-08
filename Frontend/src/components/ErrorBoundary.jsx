import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '60vh', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 16,
          padding: 40, textAlign: 'center',
        }}>
          <div style={{ fontSize: 48 }}>Something went wrong</div>
          <p style={{ color: '#64748b', fontSize: 14, maxWidth: 420 }}>
            {this.state.error?.message || 'An unexpected error occurred. Please try again.'}
          </p>
          <button className="btn btn-primary" onClick={this.handleRetry}>
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
