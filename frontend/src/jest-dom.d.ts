// `jest.setup.ts` imports @testing-library/jest-dom at runtime, but that file is
// outside tsconfig's `include`, so its global matcher augmentation never reached
// the test files and `tsc --noEmit` failed on toBeInTheDocument/toHaveValue.
// This pulls the augmentation into the compilation from inside `src/`.
import "@testing-library/jest-dom";
