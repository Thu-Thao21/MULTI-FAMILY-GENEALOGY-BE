import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from app.db.postgres import async_session_maker, init_db
from app.models.postgres import Account, AccountRole, Member, Family
from app.core.security import hash_password

async def seed_member():
    await init_db()

    async with async_session_maker() as session:
        # Check if member account already exists
        res = await session.execute(select(Account).where(Account.username == "thanhvien"))
        existing_acc = res.scalar_one_or_none()

        pwd_hash = hash_password("thanhvien123")

        # Get or create family
        fam_res = await session.execute(select(Family))
        family = fam_res.scalars().first()

        if not family:
            family = Family(
                id="fam_default_001",
                name="DONG HO NGUYEN CHI 1",
                founder_name="CU KHOI TO NGUYEN VAN A",
                origin_place="Xã Kim Liên, Nam Đàn, Nghệ An",
                status="active"
            )
            session.add(family)
            await session.commit()
            await session.refresh(family)

        # Get or create member person record
        mem_res = await session.execute(select(Member).where(Member.id == "mem_001"))
        member_person = mem_res.scalar_one_or_none()

        if not member_person:
            member_person = Member(
                id="mem_001",
                family_id=family.id,
                full_name="Nguyễn Văn A",
                gender="male",
                generation=4,
                occupation="Kỹ sư Phần mềm",
                education="Thạc sĩ Công nghệ",
                status="alive",
                is_alive=True,
                is_primary=True,
            )
            session.add(member_person)
            await session.commit()
            await session.refresh(member_person)

        if not existing_acc:
            acc = Account(
                id="acc_member_001",
                firebase_uid="firebase_member_001",
                username="thanhvien",
                email="thanhvien@giaphaviet.vn",
                display_name="Nguyễn Văn A",
                password_hash=pwd_hash,
                email_verified=True,
                status="active",
            )
            session.add(acc)
            await session.flush()

            acc_role = AccountRole(
                account_id=acc.id,
                role="member",
                family_id=family.id,
                status="active"
            )
            session.add(acc_role)

            member_person.account_id = acc.id
            await session.commit()
            print("Successfully created Member account: username=thanhvien, password=thanhvien123")
        else:
            existing_acc.password_hash = pwd_hash
            existing_acc.status = "active"
            await session.commit()
            print("Updated existing Member account: username=thanhvien, password=thanhvien123")

if __name__ == "__main__":
    asyncio.run(seed_member())
