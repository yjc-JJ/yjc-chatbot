# FastAPI 应用 Docker 部署指南

## 一、服务器环境准备

### 1.1 连接服务器

```bash
# 使用 SSH 连接到你的 Linux 服务器
ssh username@your-server-ip
```

### 1.2 更新系统

```bash
# 更新系统包（适用于 Ubuntu/Debian）
sudo apt update && sudo apt upgrade -y
```

### 1.3 安装 Docker

```bash
# 安装 Docker 依赖
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

# 添加 Docker GPG 密钥
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# 添加 Docker 软件源
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 更新包列表并安装 Docker
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io

# 验证 Docker 安装
docker --version

# 允许当前用户运行 Docker（无需 sudo）
sudo usermod -aG docker $USER

# 重新登录以生效
exit
```

### 1.4 安装 Docker Compose

```bash
# 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.6/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose

# 添加执行权限
sudo chmod +x /usr/local/bin/docker-compose

# 验证安装
docker-compose --version
```

## 二、部署应用

### 2.1 上传项目文件

使用 `scp` 命令将项目文件上传到服务器：

```bash
# 在本地执行，将项目目录上传到服务器
scp -r /path/to/your/project username@your-server-ip:/home/username/
```

### 2.2 创建环境变量文件

```bash
# 进入项目目录
cd /home/username/your-project-folder

# 创建 .env 文件
cat > .env << EOF
SECRET_KEY=your-very-secure-secret-key-here-make-it-long-and-random
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DEEPSEEK_API_KEY=your-deepseek-api-key
OPENAI_API_KEY=your-openai-api-key
EOF
```

**注意：** 请务必将 `SECRET_KEY` 替换为一个长且随机的字符串，建议至少32个字符。

### 2.3 构建镜像

```bash
# 构建 Docker 镜像
docker-compose build

# 或者使用 docker build（如果不使用 docker-compose）
# docker build -t fastapi-app .
```

### 2.4 启动容器

```bash
# 启动容器（后台模式）
docker-compose up -d

# 查看容器状态
docker-compose ps
```

## 三、服务验证

### 3.1 检查容器状态

```bash
# 查看所有运行中的容器
docker-compose ps

# 或者查看所有容器
docker ps

# 查看容器详细信息
docker inspect fastapi-app
```

### 3.2 测试 API

```bash
# 测试健康检查接口
curl http://localhost:8000/health

# 测试文档接口
curl http://localhost:8000/docs
```

### 3.3 访问应用

在浏览器中访问：
- API 文档：`http://your-server-ip:8000/docs`
- 聊天界面：`http://your-server-ip:8000/chat`
- 系统页面：`http://your-server-ip:8000/system`

## 四、日志管理

### 4.1 查看应用日志

```bash
# 查看所有日志（实时）
docker-compose logs -f

# 查看最近的日志
docker-compose logs --tail=100

# 查看指定容器的日志
docker logs fastapi-app

# 实时查看日志
docker logs -f fastapi-app
```

### 4.2 日志清理

```bash
# 清理所有容器日志（谨慎操作）
sudo sh -c "truncate -s 0 /var/lib/docker/containers/*/*-json.log"
```

## 五、常见问题排查

### 5.1 容器无法启动

```bash
# 查看容器日志
docker-compose logs

# 检查端口是否被占用
netstat -tlnp | grep 8000

# 尝试重新构建
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### 5.2 权限问题

```bash
# 如果遇到权限问题，尝试修改目录权限
sudo chown -R $USER:$USER /home/username/your-project-folder
```

### 5.3 数据库连接问题

```bash
# 检查数据库文件权限
ls -la app_data/

# 如果需要，创建数据目录
mkdir -p app_data static/avatars
```

### 5.4 内存不足

```bash
# 查看系统内存使用
free -h

# 查看容器资源使用
docker stats
```

## 六、安全最佳实践

### 6.1 基础安全配置

```bash
# 禁用 root 远程登录
sudo sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 配置防火墙
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 8000/tcp

# 查看防火墙状态
sudo ufw status
```

### 6.2 Docker 安全建议

1. **使用非 root 用户运行容器**（当前配置已使用非 root）
2. **定期更新镜像**：
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

3. **限制容器资源**：
   ```yaml
   # 在 docker-compose.yml 中添加
   deploy:
     resources:
       limits:
         cpus: '0.5'
         memory: 512M
       reservations:
         memory: 256M
   ```

4. **使用 .dockerignore**（已配置）

5. **敏感信息管理**：
   - 使用 `.env` 文件存储敏感信息
   - **永远不要将 .env 文件提交到版本控制**
   - 使用强密码和密钥

### 6.3 HTTPS 配置（推荐）

使用 Nginx 反向代理 + Let's Encrypt：

```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 配置 Nginx 反向代理
sudo cat > /etc/nginx/sites-available/fastapi << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/fastapi /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 七、常用命令

### 7.1 Docker Compose 命令

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看服务日志
docker-compose logs -f

# 查看服务状态
docker-compose ps

# 重新构建镜像
docker-compose build

# 查看容器内部
docker-compose exec app bash
```

### 7.2 Docker 命令

```bash
# 列出所有容器
docker ps -a

# 停止容器
docker stop fastapi-app

# 删除容器
docker rm fastapi-app

# 列出所有镜像
docker images

# 删除镜像
docker rmi fastapi-app

# 清理无用资源
docker system prune -f
```

## 八、备份与恢复

### 8.1 备份数据

```bash
# 备份数据库
docker-compose exec app cp /app/app_data/test.db /app/app_data/test.db.backup

# 备份整个项目目录
tar -czvf project_backup_$(date +%Y%m%d).tar.gz /home/username/your-project-folder
```

### 8.2 恢复数据

```bash
# 停止服务
docker-compose down

# 恢复数据库
cp /path/to/backup/test.db /home/username/your-project-folder/app_data/

# 启动服务
docker-compose up -d
```

## 九、故障排除流程图

```
容器无法启动
    │
    ├─→ 查看日志: docker-compose logs
    │       │
    │       ├─→ 端口被占用
    │       │       └─→ 修改端口或停止占用服务
    │       │
    │       ├─→ 权限错误
    │       │       └─→ chown -R $USER:$USER ./
    │       │
    │       ├─→ 依赖安装失败
    │       │       └─→ docker-compose build --no-cache
    │       │
    │       └─→ 配置错误
    │               └─→ 检查 .env 文件
    │
    └─→ 检查容器状态: docker-compose ps
            │
            └─→ 尝试重建: docker-compose down && docker-compose up -d
```

---

**部署成功后，你可以：**
1. 访问 `http://your-server-ip:8000/docs` 查看 API 文档
2. 访问 `http://your-server-ip:8000/chat` 使用聊天功能
3. 使用管理员账户登录后台管理系统

如有任何问题，请查看日志或联系技术支持。
