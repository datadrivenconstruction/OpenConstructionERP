import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PromoVideos, youtubeUrl } from './PromoVideos';

describe('PromoVideos', () => {
  it('shows a facade and loads the nocookie embed only after a click', () => {
    const { container } = render(<PromoVideos />);
    expect(container.querySelector('iframe')).toBeNull();
    expect(container.querySelectorAll('img[src^="https://i.ytimg.com/vi/"]')).toHaveLength(4);
    fireEvent.click(screen.getAllByRole('button', { name: /play/i })[0]!);
    const frame = container.querySelector('iframe');
    expect(frame?.getAttribute('src')).toContain('youtube-nocookie.com/embed/pTaeQRzTFxY');
  });

  it('copies the youtube url', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<PromoVideos />);
    fireEvent.click(screen.getByTestId('promo-copy-vENnh7bBVVM'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(youtubeUrl('vENnh7bBVVM')));
  });
});
