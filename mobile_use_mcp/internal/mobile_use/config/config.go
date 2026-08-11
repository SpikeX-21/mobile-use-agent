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

package config

type MobileUseConfig struct {
	AuthInfo
	BizInfo
	TosInfo
}

type AuthInfo struct {
	CurrentTime     string
	ExpiredTime     string
	AccessKeyId     string
	SecretAccessKey string
	SessionToken    string
}

type BizInfo struct {
	ACEPHost  string
	ProductId string
	DeviceId  string
}

type TosInfo struct {
	TosBucket       string
	TosRegion       string
	TosEndpoint     string
	TosAccessKey    string
	TosSecretKey    string
	TosSessionToken string
}
