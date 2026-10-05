import { Injectable, signal } from '@angular/core';
import { BrowserProvider, JsonRpcProvider } from 'ethers';

import { POLYGON_AMOY_CONFIG } from './contracts.config';

@Injectable({ providedIn: 'root' })
export class WalletService {
  readonly account = signal('');
  readonly chainId = signal<number | null>(null);

  async connect(): Promise<void> {
    const provider = this.getBrowserProvider();
    const accounts = (await provider.send('eth_requestAccounts', [])) as string[];
    const network = await provider.getNetwork();

    this.account.set(accounts[0] ?? '');
    this.chainId.set(Number(network.chainId));
  }

  async switchToPolygonAmoy(): Promise<void> {
    if (!window.ethereum?.request) {
      throw new Error('MetaMask or another EVM wallet is required.');
    }

    const chainHex = `0x${POLYGON_AMOY_CONFIG.chainId.toString(16)}`;

    try {
      await window.ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: chainHex }],
      });
    } catch {
      await window.ethereum.request({
        method: 'wallet_addEthereumChain',
        params: [
          {
            chainId: chainHex,
            chainName: POLYGON_AMOY_CONFIG.chainName,
            rpcUrls: [POLYGON_AMOY_CONFIG.rpcUrl],
            blockExplorerUrls: [POLYGON_AMOY_CONFIG.blockExplorerUrl],
            nativeCurrency: POLYGON_AMOY_CONFIG.nativeCurrency,
          },
        ],
      });
    }

    await this.connect();
  }

  async getSigner() {
    const provider = this.getBrowserProvider();
    if (!this.account()) {
      await this.connect();
    }

    return provider.getSigner();
  }

  getReadOnlyProvider(): JsonRpcProvider {
    return new JsonRpcProvider(POLYGON_AMOY_CONFIG.rpcUrl);
  }

  private getBrowserProvider(): BrowserProvider {
    if (!window.ethereum) {
      throw new Error('No injected wallet found. Install MetaMask first.');
    }

    return new BrowserProvider(window.ethereum);
  }
}