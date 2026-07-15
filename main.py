import discord
from discord.ext import commands
from discord import ui, PermissionOverwrite
import random
import string
import asyncio
import sqlite3
import os
import re
from dotenv import load_dotenv

# Configuração de Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

load_dotenv()

bot = commands.Bot(command_prefix="!", intents=intents)

# Configurações Globais (Substitua pelas IDs do seu Discord)
TOKEN = os.getenv("TOKEN_TJSP")  # Token do Bot

CATEGORY_ID = 1526670877373108454  # ID da Categoria onde os tickets serão criados

STAFF_ROLE_ID = 1526624858912461002  # ID do Cargo Autorizado (Staff / Suporte / Advogado)

BANNER_THUMBNAIL_URL = "https://cdn.discordapp.com/attachments/1525193779995480166/1526381231871365280/content.png?ex=6a57798c&is=6a56280c&hm=69ade4cea6ca76e786031fb4ac6f7f8c54ded14b44953076f2103acbf8f427bb&"  # Link da logo do seu servidor

LOG_CHANNEL_ID = 1526638882115031060  # <-- Substitua pelo ID do seu canal de logs



async def send_log(guild: discord.Guild, embed: discord.Embed):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            print(f"❌ Erro ao enviar log: {e}")


# -------------------------------------------------------------
# FUNÇÃO AUXILIAR DE VERIFICAÇÃO DE CARGO / PERMISSÃO
# -------------------------------------------------------------
def is_staff_or_admin(member: discord.Member) -> bool:
    """Verifica se o membro possui o cargo de Staff autorizado ou permissão de Administrador"""
    if member.guild_permissions.administrator:
        return True
    return any(role.id == STAFF_ROLE_ID for role in member.roles)


# -------------------------------------------------------------
# BANCO DE DADOS (SQLite)
# -------------------------------------------------------------
def init_db():
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_code TEXT PRIMARY KEY,
            channel_id INTEGER,
            user_id INTEGER,
            category TEXT,
            reason TEXT,
            claimed_by INTEGER
        )
    """)
    conn.commit()
    conn.close()

def save_ticket(code, channel_id, user_id, category, reason):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tickets (ticket_code, channel_id, user_id, category, reason, claimed_by)
        VALUES (?, ?, ?, ?, ?, NULL)
    """, (code, channel_id, user_id, category, reason))
    conn.commit()
    conn.close()

def update_claimed(channel_id, claimed_by_id):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET claimed_by = ? WHERE channel_id = ?", (claimed_by_id, channel_id))
    conn.commit()
    conn.close()

def get_ticket_by_channel(channel_id):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("SELECT ticket_code, user_id, category, reason, claimed_by FROM tickets WHERE channel_id = ?", (channel_id,))
    data = cursor.fetchone()
    conn.close()
    return data

def delete_ticket_from_db(channel_id):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tickets WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()

def generate_ticket_id():
    """Gera uma ID aleatória de 7 caracteres em caixa alta (ex: VZYN4HZ)"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))

def create_simple_embed(title, description, color=0x2b2d31):
    return discord.Embed(title=title, description=description, color=color)


# -------------------------------------------------------------
# MODAIS DO PAINEL ADMIN
# -------------------------------------------------------------
class AddUserModal(ui.Modal, title="Adicionar Usuário ao Ticket"):
    user_id = ui.TextInput(label="ID do Usuário", placeholder="Cole o ID do usuário aqui", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            member = await interaction.guild.fetch_member(int(self.user_id.value))
            await interaction.channel.set_permissions(member, view_channel=True, send_messages=True)
            embed = create_simple_embed("✅ Usuário Adicionado", f"O membro {member.mention} foi adicionado ao atendimento com sucesso.", 0x57f287)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            embed = create_simple_embed("❌ Erro", "Não foi possível encontrar ou adicionar o usuário. Verifique se o ID está correto.", 0xFFD700)
            await interaction.response.send_message(embed=embed, ephemeral=True)

class RemoveUserModal(ui.Modal, title="Remover Usuário do Ticket"):
    user_id = ui.TextInput(label="ID do Usuário", placeholder="Cole o ID do usuário aqui", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            member = await interaction.guild.fetch_member(int(self.user_id.value))
            await interaction.channel.set_permissions(member, overwrite=None)
            embed = create_simple_embed("✅ Usuário Removido", f"O membro {member.mention} foi removido do atendimento.", 0x57f287)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            embed = create_simple_embed("❌ Erro", "Não foi possível remover o usuário. Verifique o ID digitado.", 0xFFD700)
            await interaction.response.send_message(embed=embed, ephemeral=True)

class RenameTicketModal(ui.Modal, title="Renomear Ticket"):
    new_name = ui.TextInput(label="Novo Nome do Canal", placeholder="ex: ticket-resolvido", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.channel.edit(name=self.new_name.value)
        embed = create_simple_embed("✏️ Ticket Renomeado", f"O nome do canal foi alterado para: **{self.new_name.value}**", 0x5865f2)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# -------------------------------------------------------------
# BOTÃO DE LINK DIRETO PARA O TICKET (PARA O PRIVADO)
# -------------------------------------------------------------
class TicketLinkView(ui.View):
    def __init__(self, channel_url):
        super().__init__(timeout=None)
        self.add_item(ui.Button(label="Ir para o Ticket", url=channel_url, style=discord.ButtonStyle.link, emoji="🔗"))


# -------------------------------------------------------------
# SELECT MENU DO PAINEL ADMIN (RESTRITO)
# -------------------------------------------------------------
class AdminPanelSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Adicionar Usuário(s)", description="Adiciona usuários ao atendimento.", value="add_user", emoji="<:ADD:1526751859388317806>"),
            discord.SelectOption(label="Remover Usuário(s)", description="Remove usuários do atendimento.", value="remove_user", emoji="<:REMOVER:1526753500862611456>"),
            discord.SelectOption(label="Notificar Autor", description="Envia aviso pré-definido no privado do autor.", value="notify_author", emoji="<:SINO:1526752039596458086>"),
            discord.SelectOption(label="Renomear Ticket", description="Altera o nome do atendimento.", value="rename_ticket", emoji="<:EDITAR:1526752123046334465>"),
            discord.SelectOption(label="Largar Ticket", description="Deixa de ser o responsável pelo atendimento.", value="unclaim_ticket", emoji="<:LARGAR:1526752256811077653>"),
        ]
        super().__init__(placeholder="Selecione uma opção de administração...", options=options, custom_id="admin_panel_select")

    async def callback(self, interaction: discord.Interaction):
        # Checagem de permissão
        if not is_staff_or_admin(interaction.user):
            no_perm_embed = create_simple_embed("❌ Acesso Negado", "Apenas a equipe autorizada pode gerenciar este atendimento.", 0xFFD700)
            return await interaction.response.send_message(embed=no_perm_embed, ephemeral=True)

        choice = self.values[0]

        if choice == "add_user":
            await interaction.response.send_modal(AddUserModal())

        elif choice == "remove_user":
            await interaction.response.send_modal(RemoveUserModal())

        elif choice == "notify_author":
            ticket_data = get_ticket_by_channel(interaction.channel.id)
            if ticket_data:
                user_id = ticket_data[1]
                try:
                    target_user = await interaction.client.fetch_user(user_id)
                    dm_embed = discord.Embed(
                        title="🔔 Atualização no seu Atendimento TJSP",
                        description=(
                            f"Olá {target_user.mention}, seu atendimento teve uma atualização.\n\n"
                            "Para olhar o ticket, clique no botão abaixo para ser redirecionado ao seu atendimento."
                        ),
                        color=0x2b2d31
                    )
                    if BANNER_THUMBNAIL_URL:
                        dm_embed.set_thumbnail(url=BANNER_THUMBNAIL_URL)

                    view = TicketLinkView(channel_url=interaction.channel.jump_url)
                    await target_user.send(embed=dm_embed, view=view)

                    success_embed = create_simple_embed("✅ Autor Notificado", f"A notificação foi enviada com sucesso para {target_user.mention}.", 0xFFD700)
                    await interaction.response.send_message(embed=success_embed, ephemeral=True)
                except Exception:
                    error_embed = create_simple_embed("❌ Erro no Envio", "Não foi possível notificar o autor (DM fechada ou ID inválida).", 0xFFD700)
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
            else:
                error_embed = create_simple_embed("❌ Erro", "Não foi possível identificar o autor deste ticket no Banco de Dados.", 0xFFD700)
                await interaction.response.send_message(embed=error_embed, ephemeral=True)

        elif choice == "rename_ticket":
            await interaction.response.send_modal(RenameTicketModal())

        elif choice == "unclaim_ticket":
            await interaction.response.defer(ephemeral=True)
            async for message in interaction.channel.history(limit=10, oldest_first=True):
                if message.author == interaction.client.user and message.embeds:
                    embed = message.embeds[0]
                    embed.set_field_at(2, name="👤 Assumido por:", value="`Ninguém`", inline=False)
                    
                    update_claimed(interaction.channel.id, None)

                    new_view = TicketControlView()
                    await message.edit(embed=embed, view=new_view)

                    confirm_embed = create_simple_embed("🚪 Ticket Desassumido", "Você deixou a responsabilidade deste atendimento com sucesso.", 0xfee75c)
                    await interaction.followup.send(embed=confirm_embed, ephemeral=True)

                    channel_notice = create_simple_embed("⚠️ Status Atualizado", f"{interaction.user.mention} deixou de ser o responsável por este atendimento.", 0xfee75c)
                    await interaction.channel.send(embed=channel_notice)
                    break

class AdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AdminPanelSelect())


# -------------------------------------------------------------
# BOTÕES DO PAINEL DENTRO DO TICKET (RESTRITOS)
# -------------------------------------------------------------
class TicketControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Assumir Ticket", style=discord.ButtonStyle.secondary, emoji="<:assumirticket:1526748343978561547>", custom_id="assumir_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: ui.Button):
        # Checagem de permissão
        if not is_staff_or_admin(interaction.user):
            no_perm_embed = create_simple_embed("❌ Acesso Negado", "Apenas a equipe autorizada pode assumir atendimentos.", 0xFFD700)
            return await interaction.response.send_message(embed=no_perm_embed, ephemeral=True)

        embed = interaction.message.embeds[0]
        embed.set_field_at(2, name="<:111:1526738453511934023> Assumido por:", value=interaction.user.mention, inline=False)

        update_claimed(interaction.channel.id, interaction.user.id)

        # Define o emoji customizado diretamente na propriedade emoji do botão
        button.emoji = discord.PartialEmoji.from_str(
            "<:ticketassumido:1526748366015565904>"
        )
        button.label = "Ticket Assumido"
        button.disabled = True
        button.style = discord.ButtonStyle.secondary

        await interaction.message.edit(embed=embed, view=self)

        confirm_embed = create_simple_embed("✅ Ticket Assumido", "Você assumiu este atendimento com sucesso!", 0x57f287)
        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)

        notice_embed = create_simple_embed("🛠️ Atendimento Assumido", f"O atendimento foi assumido por {interaction.user.mention}.", 0xFFD700)
        await interaction.channel.send(embed=notice_embed)

# ---------------- LOG: TICKET ASSUMIDO ----------------
        ticket_data = get_ticket_by_channel(interaction.channel.id)
        ticket_code = ticket_data[0] if ticket_data else "Desconhecido"

        log_embed = discord.Embed(
            title=f"<:ticketassumido:1526748366015565904> O membro da equipe ({interaction.user.mention}) assumiu o atendimento `{ticket_code}`", color=0x5865F2
        )

        await send_log(interaction.guild, log_embed)        

    @ui.button(label="Painel Admin", style=discord.ButtonStyle.secondary, emoji="<:paineladmin:1526748297564389558>⚙️", custom_id="painel_admin_btn")
    async def admin_panel(self, interaction: discord.Interaction, button: ui.Button):
        # Checagem de permissão
        if not is_staff_or_admin(interaction.user):
            no_perm_embed = create_simple_embed("❌ Acesso Negado", "Apenas a equipe autorizada pode acessar o Painel Admin.", 0xFFD700)
            return await interaction.response.send_message(embed=no_perm_embed, ephemeral=True)

        admin_embed = create_simple_embed("⚙️ Painel de Administração", "Selecione na lista abaixo a ação de gerenciamento que deseja executar neste ticket.")
        await interaction.response.send_message(embed=admin_embed, view=AdminPanelView(), ephemeral=True)

    @ui.button(label="Finalizar Ticket", style=discord.ButtonStyle.secondary, emoji="<:fecharticket:1526748323527262248>", custom_id="fechar_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        # Checagem de permissão
        if not is_staff_or_admin(interaction.user):
            no_perm_embed = create_simple_embed("❌ Acesso Negado", "Apenas a equipe autorizada pode encerrar este atendimento.", 0xFFD700)
            return await interaction.response.send_message(embed=no_perm_embed, ephemeral=True)
        
# ---------------- LOG: TICKET FECHADO ----------------
        ticket_data = get_ticket_by_channel(interaction.channel.id)
        if ticket_data:
            ticket_code, user_id, category, reason, claimed_by = ticket_data

            author_mention = f"<@{user_id}>"
            claimed_mention = f"<@{claimed_by}>" if claimed_by else "`Ninguém`"

            log_embed = discord.Embed(
                title=f"<:fecharticket:1526748323527262248> O membro da equipe ({interaction.user.mention}) finalizou o atendimento `{ticket_code}`", color=0xED4245
            )

            await send_log(interaction.guild, log_embed)        

        close_embed = create_simple_embed("🔒 Encerrando Ticket", "Este atendimento será fechado e deletado em **5 segundos**...", 0xFFD700)
        await interaction.response.send_message(embed=close_embed, ephemeral=True)
        delete_ticket_from_db(interaction.channel.id)
        await asyncio.sleep(5)
        await interaction.channel.delete()


# -------------------------------------------------------------
# SELECT MENU INICIAL DA CENTRAL DE ATENDIMENTO (PÚBLICO)
# -------------------------------------------------------------
class TicketSelectMenu(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Solicitar Mandado", value="Solicitar Mandado", emoji="<:MANDADO:1526747021766295645>"),
            discord.SelectOption(label="Solicitar OAB", value="Solicitar OAB", emoji="<:OAB:1526746980758589490> "),
            discord.SelectOption(label="Solicitar Provas Práticas", value="Solicitar Provas Práticas", emoji="<:PROVASPRTICAS:1526747060626264125> "),
            discord.SelectOption(label="Solicitar Alvarás", value="Solicitar Alvarás", emoji="<:ALVARAS:1526747126972026930> "),
            discord.SelectOption(label="Solicitar Certidões", value="Solicitar Certidões", emoji="<:CERTIDOES:1526747190465396807>"),
            discord.SelectOption(label="Solicitar Advogado", value="Solicitar Advogado", emoji="<:ADVOGADO:1526747222169882875>"),
        ]
        super().__init__(placeholder="Selecione o serviço desejado...", options=options, custom_id="ticket_main_select")

    async def callback(self, interaction: discord.Interaction):
        # Todos os membros do servidor podem usar esta opção para abrir o ticket
        await interaction.response.defer(ephemeral=True)
        motivo = self.values[0]
        guild = interaction.guild
        user = interaction.user

        category = guild.get_channel(CATEGORY_ID)
        staff_role = guild.get_role(STAFF_ROLE_ID)

        overwrites = {
            guild.default_role: PermissionOverwrite(view_channel=False),
            user: PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            staff_role: PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        }

        ticket_code = generate_ticket_id()
        channel_name = f"🎟️・{ticket_code.lower()}"

        ticket_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)

        # Salva o ticket no SQLite
        save_ticket(ticket_code, ticket_channel.id, user.id, "Suporte", motivo)

        embed = discord.Embed(
            title=f"Ticket {ticket_code}",
            description=(
                f"> {user.mention} Seja bem-vindo(a) ao sistema de atendimento.\n"
                "> Através deste canal, a equipe irá realizar seu atendimento e esclarecer suas dúvidas!\n"
                "> Envie abaixo sua solicitação e aguarde.\n\n"
                "------------------------------------------\n"
            ),
            color=0xFFD700
        )
        if BANNER_THUMBNAIL_URL:
            embed.set_thumbnail(url=BANNER_THUMBNAIL_URL)

        embed.add_field(
            name="<:222:1526738486126972929> Motivo do contato:",
            value=f"`{motivo}`",
            inline=False,
        )
        embed.add_field(
            name="------------------------------------------",
            value="",
            inline=False
        )
        embed.add_field(
            name="<:111:1526738453511934023> Assumido por:",
            value="`Ninguém`",
            inline=False
        )
        embed.add_field(
            name="------------------------------------------",
            value="",
            inline=False
        )

        await ticket_channel.send(content=f"{user.mention} | {staff_role.mention}", embed=embed, view=TicketControlView())

        created_embed = create_simple_embed("✅ Ticket Criado", f"Seu atendimento foi aberto com sucesso em {ticket_channel.mention}.", 0xFFD700)
        await interaction.followup.send(embed=created_embed, ephemeral=True)

# ---------------- LOG: TICKET CRIADO ----------------

        from datetime import datetime

        # Pega o horário de abertura
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Pega o horário de encerramento
        agora_encerrado = datetime.now().strftime("%d/%m/%Y %H:%M")

        log_embed = discord.Embed(
            title=f"<:pessoas:1526764699490713662> Aberto por: {interaction.user.mention} ({interaction.user.id})",
            description=
            f"<:ticketassumido:1526748366015565904> Assumido por: `Ninguém`\n"
            f"<:pessoas:1526764699490713662> Finalizado por: `Ninguém`\n"
            f"Ticket criado: {ticket_code}\n"
            f"<:hora:1526766169468567612> Aberto em: {agora}\n"
            f"<:hora:1526766169468567612> Encerrado em: {agora_encerrado}\n",
            color=0x57F287,
        )


        await send_log(guild, log_embed)

class TicketSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelectMenu())


# -------------------------------------------------------------
# EVENTOS E REGISTRO DAS VIEWS PERSISTENTES
# -------------------------------------------------------------
@bot.event
async def on_ready():
    init_db()

    bot.add_view(TicketSelectView())
    bot.add_view(TicketControlView())
    bot.add_view(AdminPanelView())

    print(f"🤖 Bot online como: {bot.user.name}")
    print("💾 Banco de dados SQLite e Permissões ativadas!")

@bot.command(name="TJSP", help="Configura o painel de atendimento no canal atual. (Apenas Staff)")
@commands.has_role(STAFF_ROLE_ID) # <-- Apenas quem tem a ID do cargo STAFF_ROLE_ID pode usar
async def setup_ticket(ctx):
    await ctx.message.delete()

    embed = discord.Embed(
        title="**Central de Atendimento Jurídico**",
        description=(
            "Seja bem-vindo(a) ao sistema de atendimento da Jardim Peri. Através do atendimento, \n"
            "você pode falar diretamente com nossa equipe.\n\n"
            "**Horário de Atendimento:** 08:00 - 00:00\n"
        ),
        color=0x2b2d31
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1444735189765849320/1526692086819328070/Criadores_JP_2.png?ex=6a57f24e&is=6a56a0ce&hm=bf9be846df71c7aaf6fcde4fb34b1ea6f5d1bea025602164ffd57cb31df7e4d5&")  

    embed.set_footer(text="Jardim Peri RP - Todos os direitos reservados © 2026", icon_url="https://cdn.discordapp.com/attachments/1444735189765849320/1526686691786752091/brasao_tjsp.webp?ex=6a57ed47&is=6a569bc7&hm=c555658dc71cdb0ff38827ff2225014d22a773d706495cc7c810e97dc6b32532&")

    await ctx.send(embed=embed, view=TicketSelectView())

@setup_ticket.error
async def setup_ticket_error(ctx, error):
    if isinstance(error, commands.MissingRole) or isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Acesso Negado",
            description="Apenas membros da equipe autorizada podem executar o setup.",
            color=0xFFD700
        )
        await ctx.send(embed=embed, delete_after=5)

print(TOKEN)  # Adicione esta linha para depuração do token
bot.run(TOKEN)