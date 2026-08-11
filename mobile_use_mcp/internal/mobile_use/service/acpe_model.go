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

package service

type AppItem struct {
	AppID       string `json:"app_id"`
	AppName     string `json:"app_name"`
	AppStatus   string `json:"app_status"`
	PackageName string `json:"package_name"`
}

type TosConfig struct {
	AccessKey    string
	SecretKey    string
	SessionToken string
	Bucket       string
	Region       string
	Endpoint     string
}

type ScreenShotResult struct {
	ScreenshotURL string `json:"screenshot_url"`
	Width         int    `json:"width"`
	Height        int    `json:"height"`
}
