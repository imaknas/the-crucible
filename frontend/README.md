# The Crucible - Frontend ⚔️

A high-performance React interface for non-linear AI debate, built with Next.js and React Flow.

## 🚀 Getting Started

### Prerequisites

- Node.js 24+
- `npm` (v10+)

### Installation

```bash
npm install
```

### Development

```bash
npm run dev
```

The application will be available at [http://localhost:3000](http://localhost:3000).

## 🏗️ Architecture

- **`ChatView.tsx`**: The primary message renderer, supporting Markdown, LaTeX, and **Sources Cited** accordions for RAG citations.
- **`TreeCanvas.tsx`**: The conversation tree visualizer built on React Flow. Supports custom node rendering and persistent layout.
- **`ControlPanel.tsx`**: Unified interface for model selection, system toggles (including **Deep Knowledge Search**), and arena configuration.
- **`useChatWebSocket.ts`**: Custom hook managing the complex WebSocket communication flow.

## 🧪 Testing

We use Jest and React Testing Library for component and hook validation.

```bash
# Run all tests
npm test

# Run specific component tests
npm test src/components/ChatView.test.tsx
```

## 🎨 Styling

The project uses **Material UI (MUI)** for the component library and **Framer Motion** for micro-interactions. The design system focuses on a sleek, dark-mode focused aesthetic ("The Council").

---

Build with intention. Refine with The Crucible.
