from fastapi import FastAPI, HTTPException, Depends, status
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    DateTime,
    Boolean,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List
from datetime import datetime
import uvicorn

# Database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./restaurant.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Database Models
class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    price = Column(Float)
    category = Column(String)
    is_available = Column(Boolean, default=True)
    order_items = relationship("OrderItem", back_populates="menu_item")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    table_number = Column(Integer)
    status = Column(String)  # pending, preparing, served, paid
    created_at = Column(DateTime, default=datetime.utcnow)
    total_amount = Column(Float, default=0.0)
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"))
    quantity = Column(Integer)
    unit_price = Column(Float)
    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")


# Pydantic models for request/response
class MenuItemBase(BaseModel):
    name: str
    description: str
    price: float
    category: str
    is_available: bool = True


class MenuItemCreate(MenuItemBase):
    pass


class MenuItemResponse(MenuItemBase):
    id: int

    class Config:
        orm_mode = True


class OrderItemBase(BaseModel):
    menu_item_id: int
    quantity: int


class OrderCreate(BaseModel):
    table_number: int
    items: List[OrderItemBase]


class OrderItemResponse(OrderItemBase):
    id: int
    unit_price: float

    class Config:
        orm_mode = True


class OrderResponse(BaseModel):
    id: int
    table_number: int
    status: str
    created_at: datetime
    total_amount: float
    items: List[OrderItemResponse]

    class Config:
        orm_mode = True


# FastAPI app
app = FastAPI(title="Restaurant Management API")


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# API Routes - Menu Items
@app.post("/menu-items/", response_model=MenuItemResponse)
def create_menu_item(item: MenuItemCreate, db: Session = Depends(get_db)):
    db_item = MenuItem(**item.dict())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@app.get("/menu-items/", response_model=List[MenuItemResponse])
def read_menu_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(MenuItem).offset(skip).limit(limit).all()
    return items


@app.get("/menu-items/{item_id}", response_model=MenuItemResponse)
def read_menu_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return item


@app.put("/menu-items/{item_id}", response_model=MenuItemResponse)
def update_menu_item(item_id: int, item: MenuItemCreate, db: Session = Depends(get_db)):
    db_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if db_item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    for key, value in item.dict().items():
        setattr(db_item, key, value)

    db.commit()
    db.refresh(db_item)
    return db_item


@app.delete("/menu-items/{item_id}")
def delete_menu_item(item_id: int, db: Session = Depends(get_db)):
    db_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if db_item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    db.delete(db_item)
    db.commit()
    return {"message": "Menu item deleted"}


# API Routes - Orders
@app.post("/orders/", response_model=OrderResponse)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    db_order = Order(table_number=order.table_number, status="pending")
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    total_amount = 0
    try:
        for item in order.items:
            menu_item = (
                db.query(MenuItem).filter(MenuItem.id == item.menu_item_id).first()
            )
            if not menu_item:
                raise HTTPException(
                    status_code=404, detail=f"Menu item {item.menu_item_id} not found"
                )

            order_item = OrderItem(
                order_id=db_order.id,
                menu_item_id=item.menu_item_id,
                quantity=item.quantity,
                unit_price=menu_item.price,
            )
            total_amount += menu_item.price * item.quantity
            db.add(order_item)

        db_order.total_amount = total_amount
        db.commit()
        db.refresh(db_order)

    except Exception:
        db.rollback()
        raise

    return db_order


@app.get("/orders/", response_model=List[OrderResponse])
def read_orders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    orders = db.query(Order).offset(skip).limit(limit).all()
    return orders


@app.get("/orders/{order_id}", response_model=OrderResponse)
def read_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@app.put("/orders/{order_id}/status")
def update_order_status(order_id: int, status: str, db: Session = Depends(get_db)):
    valid_statuses = ["pending", "preparing", "served", "paid"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = status
    db.commit()
    return {"message": f"Order status updated to {status}"}


if __name__ == "__main__":
    # Create database tables
    Base.metadata.create_all(bind=engine)
    # Run the application
    uvicorn.run(app, host="0.0.0.0", port=8000)
