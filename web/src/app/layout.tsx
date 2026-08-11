// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// Licensed under the 【火山方舟】原型应用软件自用许可协议
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at 
//     https://www.volcengine.com/docs/82379/1433703
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import type { Metadata } from 'next';
import { Toaster } from '@/components/ui/sonner';
import './globals.css';
import { VePhonePreloader } from '@/components/common/VePhonePreloader';

export const metadata: Metadata = {
  title: 'Mobile Use',
  description: 'Mobile Use Agent is All You Need.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
      <VePhonePreloader />
      <main
          style={{
            background: 'linear-gradient(77.86deg, #EBF7FF -3.23%, #E6EEFF 51.11%, #F8F0FF 98.65%)',
          }}
        >
          {children}
        </main>
        <Toaster />
      </body>
    </html>
  );
}
